"""Configurator chain — renders project-level files from current workspace settings.

Triggered explicitly from mutator endpoints (project register, workspace create,
project/device phase-settings save, module toggle) and from app startup. No event bus.
"""

import json
import logging
import os
import shutil
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

from core.paths import (
    DEFAULT_AGENTS_DIR,
    DEFAULT_MODULES_DIR,
    DEFAULT_MODULES_LOCAL_DIR,
    DEFAULT_SKILLS_DIR,
    hook_command,
)
from services.modules_discovery import resolve_enabled_module_overrides

log = logging.getLogger(__name__)

_MODULE_OVERRIDE_ROOTS = [DEFAULT_MODULES_DIR, DEFAULT_MODULES_LOCAL_DIR]


def _on_off(flag: bool) -> str:
    return "ON" if flag else "OFF"


def _active_workspaces(db: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT id, project_id, working_dir, workflow_mode "
        "FROM workspaces WHERE project_id = ? AND status = 'active'",
        (project_id,),
    ).fetchall()


def _active_worktree_paths(db: sqlite3.Connection, project_id: int) -> list[str]:
    return [ws["working_dir"] for ws in _active_workspaces(db, project_id) if ws["working_dir"]]


def _atomic_write_text(path: Path, content: str) -> None:
    """Write *content* to *path* via a sibling temp file and ``os.replace``.

    The temp file always lives in the target's directory so ``os.replace`` is an
    atomic rename rather than a cross-filesystem copy.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def _atomic_copy2(src: Path, dst: Path) -> None:
    """Copy *src* onto *dst* atomically via a sibling temp file in *dst*'s directory."""
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _rendered(target: str) -> dict:
    return {"target": target, "action": "rendered", "reason": None}


def _skipped(target: str, reason: str) -> dict:
    return {"target": target, "action": "skipped", "reason": reason}


class Configurator(ABC):
    """Renders one piece of project/worktree configuration from current DB state."""

    @abstractmethod
    def configure(
        self, db: sqlite3.Connection, project_id: int, project_path: Path
    ) -> list[dict]:
        """Apply this configurator for the given project. Idempotent — safe to re-run.

        Returns one result entry per target with shape
        ``{'target': str, 'action': 'rendered'|'skipped'|'failed', 'reason': str|None}``.
        """

    def configure_workspace(
        self, db: sqlite3.Connection, project: sqlite3.Row, ws: sqlite3.Row
    ) -> list[dict]:
        """Re-render only the artifacts that differ per workspace, for one worktree.

        Default no-op: configurators whose output is identical across a
        project's worktrees have nothing to do for a single-workspace refresh.
        Overridden by :class:`SkillConfigurator`, whose SKILL.md is rendered
        from the workspace-scope phase set.
        """
        return []


class SkillConfigurator(Configurator):
    """Renders SKILL.md from the engine's SKILL.md.template + each enabled phase's
    description_for_skill().

    Unlike the other configurators this also writes the project root so a fresh
    install seeds the canonical SKILL.md before any worktree exists; active
    worktrees additionally receive their own copy.

    The template is always read from the shipped engine default. Project-local
    template copies are never customizations — they are installer-seeded snapshots
    that go stale — so rendering off the engine template is the single source of
    truth and prevents stale gates from re-materializing on every render.
    """

    TEMPLATE_REL_PATH = ".claude/skills/governed-workflow/SKILL.md.template"
    OUTPUT_REL_PATH = ".claude/skills/governed-workflow/SKILL.md"
    DEFAULT_TEMPLATE_PATH = DEFAULT_SKILLS_DIR / "governed-workflow" / "SKILL.md.template"
    TEMPLATE_OVERRIDE_REL_PATH = "governed-workflow/SKILL.md.template"
    PLACEHOLDER_PHASES = "{{PHASES}}"
    PLACEHOLDER_PHASE_MAP = "{{PHASE_MAP}}"

    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> list[dict]:
        project_path = Path(project_path)
        template, skip = self._load_engine_template(db)
        if template is None:
            return [skip]

        simple_planning = self._fetch_simple_planning(db, project_id)
        results = [self._render_project_root(db, project_id, project_path, template, simple_planning)]
        for ws in _active_workspaces(db, project_id):
            if ws["working_dir"]:
                results.append(self._render_workspace(db, template, simple_planning, ws))
        return results

    def configure_workspace(
        self, db: sqlite3.Connection, project: sqlite3.Row, ws: sqlite3.Row
    ) -> list[dict]:
        template, skip = self._load_engine_template(db)
        if template is None:
            return [skip]
        if not ws["working_dir"]:
            return [_skipped("SKILL.md", "workspace has no working_dir")]
        simple_planning = self._fetch_simple_planning(db, project["id"])
        return [self._render_workspace(db, template, simple_planning, ws)]

    def _resolve_template_path(self, db: sqlite3.Connection) -> Path:
        """Pick the SKILL.md.template source: last-enabled module override, else the engine default."""
        overrides = resolve_enabled_module_overrides(db, "skills", _MODULE_OVERRIDE_ROOTS)
        override_path = overrides.get(self.TEMPLATE_OVERRIDE_REL_PATH)
        if override_path is not None:
            log.debug("SkillConfigurator: using module override template %s", override_path)
            return override_path
        log.debug("SkillConfigurator: using engine default template %s", self.DEFAULT_TEMPLATE_PATH)
        return self.DEFAULT_TEMPLATE_PATH

    def _load_engine_template(self, db: sqlite3.Connection) -> tuple[str | None, dict | None]:
        """Read and validate the resolved template. Returns (template, None) or (None, skip)."""
        template_path = self._resolve_template_path(db)
        if not template_path.exists():
            log.warning(
                "SkillConfigurator: engine template missing at %s, skipping",
                template_path,
            )
            return None, _skipped("SKILL.md", "template missing")
        template = template_path.read_text()
        if self.PLACEHOLDER_PHASES not in template:
            log.warning(
                "SkillConfigurator: template at %s lacks %s placeholder, skipping",
                template_path,
                self.PLACEHOLDER_PHASES,
            )
            return None, _skipped("SKILL.md", "template missing placeholder")
        return template, None

    def _render_project_root(
        self, db: sqlite3.Connection, project_id: int, project_path: Path,
        template: str, simple_planning: bool,
    ) -> dict:
        """Render the canonical project-scope SKILL.md seed at the project root."""
        target = project_path / self.OUTPUT_REL_PATH
        if not project_path.exists():
            log.warning(
                "SkillConfigurator: project path %s missing, skipping project-root render",
                project_path,
            )
            return _skipped(str(target), "project path missing")
        from services import phase_resolver

        phase_ids = phase_resolver.resolve_for_project(db, project_id, include_templated=True)
        rendered = self.render(template, phase_ids, simple_planning=simple_planning)
        return self._write_target(target, rendered)

    def _render_workspace(
        self, db: sqlite3.Connection, template: str, simple_planning: bool, ws: sqlite3.Row,
    ) -> dict:
        """Render SKILL.md for a single worktree using its workspace-scope phase set."""
        from services import phase_resolver

        phase_ids = phase_resolver.resolve_for_workspace(db, ws["id"], include_templated=True)
        workflow_mode = ws["workflow_mode"] if "workflow_mode" in ws.keys() else "standard"
        rendered = self.render(
            template, phase_ids, simple_planning=simple_planning, workflow_mode=workflow_mode
        )
        return self._write_target(Path(ws["working_dir"]) / self.OUTPUT_REL_PATH, rendered)

    @classmethod
    def render(
        cls, template: str, phase_ids: list[str],
        simple_planning: bool = False, workflow_mode: str = "standard",
    ) -> str:
        """Substitute the {{PHASES}} and {{PHASE_MAP}} placeholders for *phase_ids*.

        When simple_planning is True, {{#FULL_PLANNING}}...{{/FULL_PLANNING}} blocks
        are removed entirely. When False, the markers are stripped and the inner
        content is kept (full-mode rendering). ``workflow_mode`` is threaded into
        each phase's ``description_for_skill`` for mode-specific rendering, and
        also gates {{#STANDARD_MODE}}...{{/STANDARD_MODE}} /
        {{#FAST_MODE}}...{{/FAST_MODE}} blocks in the fixed template text —
        the non-matching mode's block is removed, the matching mode's markers
        are stripped and its content kept.
        """
        rendered = template.replace(
            cls.PLACEHOLDER_PHASES, cls._build_phase_block(phase_ids, simple_planning, workflow_mode)
        ).replace(
            cls.PLACEHOLDER_PHASE_MAP, cls._build_phase_map(phase_ids)
        )
        rendered = cls._apply_full_planning_blocks(rendered, simple_planning)
        return cls._apply_workflow_mode_blocks(rendered, workflow_mode)

    @staticmethod
    def _fetch_simple_planning(db: sqlite3.Connection, project_id: int | str | None) -> bool:
        """Read the simple_planning flag for the project; returns False when not found."""
        if project_id is None:
            return False
        row = db.execute(
            "SELECT simple_planning FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return bool(row["simple_planning"]) if row else False

    @staticmethod
    def _build_phase_block(
        phase_ids: list[str], simple_planning: bool = False, workflow_mode: str = "standard",
    ) -> str:
        """Concatenate each enabled phase's description_for_skill() in resolved order.

        Skips phases without a registered instance or with an empty description.
        """
        from advance.phases import get_phase  # avoid circular import at module load

        blocks = []
        for pid in phase_ids:
            phase = get_phase(pid)
            if phase is None:
                continue
            block = phase.description_for_skill(
                simple_planning=simple_planning, workflow_mode=workflow_mode
            ).strip()
            if block:
                blocks.append(block)
        return "\n\n---\n\n".join(blocks)

    @staticmethod
    def _apply_full_planning_blocks(content: str, simple_planning: bool) -> str:
        """Strip {{#FULL_PLANNING}}...{{/FULL_PLANNING}} conditional blocks.

        When simple_planning is False (full mode): strip the markers and keep the
        inner content. When True (simple mode): remove the entire block including
        the markers and their enclosed content.
        """
        import re

        if simple_planning:
            pattern = r'\{\{#FULL_PLANNING\}\}.*?\{\{/FULL_PLANNING\}\}'
            return re.sub(pattern, '', content, flags=re.DOTALL)

        content = content.replace('{{#FULL_PLANNING}}', '')
        content = content.replace('{{/FULL_PLANNING}}', '')
        return content

    @staticmethod
    def _apply_workflow_mode_blocks(content: str, workflow_mode: str) -> str:
        """Strip {{#STANDARD_MODE}}/{{#FAST_MODE}} conditional blocks for *workflow_mode*.

        The block matching the active mode has its markers stripped and its
        content kept; the other mode's block is removed entirely, markers and
        content alike. Mirrors ``_apply_full_planning_blocks``.
        """
        import re

        is_fast = workflow_mode == "fast"
        drop_tag = "FAST_MODE" if not is_fast else "STANDARD_MODE"
        keep_tag = "STANDARD_MODE" if not is_fast else "FAST_MODE"

        content = re.sub(
            r'\{\{#' + drop_tag + r'\}\}.*?\{\{/' + drop_tag + r'\}\}', '', content, flags=re.DOTALL
        )
        content = re.sub(
            r'\{\{#' + keep_tag + r'\}\}(.*?)\{\{/' + keep_tag + r'\}\}', r'\1', content, flags=re.DOTALL
        )
        return content

    @staticmethod
    def _build_phase_map(phase_ids: list[str]) -> str:
        """Render the Phase Map as a Markdown table.

        Columns: Phase, Name, What happens, Edits, Commits, Push, Gate.
        Permission columns are sourced from
        ``advance.permissions.get_phase_permissions`` so the table cannot drift
        from the runtime permission policy. Phases without a registered
        instance or without a ``short_description`` are omitted.
        """
        from advance.permissions import get_phase_permissions
        from advance.phases import get_phase

        header = (
            "| Phase | Name | What happens | Edits | Commits | Push | Gate |\n"
            "|-------|------|--------------|-------|---------|------|------|"
        )
        rows = [header]
        for pid in phase_ids:
            phase = get_phase(pid)
            if phase is None:
                continue
            summary = phase.short_description.strip()
            if not summary:
                continue
            edits, commits, push = get_phase_permissions(pid)
            gate = "USER" if phase.is_user_gate else "—"
            rows.append(
                f"| `{pid}` | {phase.name} | {summary} | "
                f"{_on_off(edits)} | {_on_off(commits)} | {_on_off(push)} | {gate} |"
            )
        return "\n".join(rows)

    def _write_target(self, path: Path, content: str) -> dict:
        _atomic_write_text(path, content)
        log.info("SkillConfigurator: wrote %s (%d bytes)", path, len(content))
        return _rendered(str(path))


class AgentFilesConfigurator(Configurator):
    """Mirrors the composed agent set into every active worktree's ``.claude/agents/``.

    The composed set layers three sources, each overwriting the last on a
    filename collision: ``claude/agents/*.md`` from the governed-workflow
    install, then enabled modules' ``override/agents/`` files (later-enabled
    module wins), then the project's own ``.claude/agents/*.md`` (project
    always wins). This lets a project-local agent customization survive a
    re-render, and lets disabling a module revert its override on the next
    render, while still keeping every worktree in lock-step otherwise.

    On each run every file in the composed set is copied (overwriting if
    present), and any ``*.md`` under the worktree's ``.claude/agents/`` that is
    not in the composed set is removed — otherwise a renamed/retired agent
    (e.g. the collapsed ``logic-reviewer`` / ``security-reviewer``) would
    linger and continue to be advertised by Claude Code.

    If the composed set is empty (no defaults, no overrides, no project-local
    agents), the configurator skips silently.

    This configurator deliberately covers active worktrees only — the project
    root is never an execution workspace, so its ``.claude/agents/`` does not
    need the canonical agent set rendered into it (it is only ever read from,
    as the project-local layer of the composed set).
    """

    OUTPUT_REL_DIR = Path(".claude") / "agents"

    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> list[dict]:
        project_path = Path(project_path)
        default_agents, empty_reason = self._default_agent_sources()

        composed: dict[str, Path] = dict(default_agents)
        composed.update(resolve_enabled_module_overrides(db, "agents", _MODULE_OVERRIDE_ROOTS))
        project_agents_dir = project_path / self.OUTPUT_REL_DIR
        if project_agents_dir.is_dir():
            composed.update(
                {p.name: p for p in sorted(project_agents_dir.glob("*.md")) if p.is_file()}
            )

        if not composed:
            log.warning("AgentFilesConfigurator: %s, skipping", empty_reason)
            return [_skipped("agents", empty_reason)]

        results = []
        for working_dir in _active_worktree_paths(db, project_id):
            target_dir = Path(working_dir) / self.OUTPUT_REL_DIR
            self._sync_directory(composed, target_dir)
            results.append(_rendered(str(target_dir)))
        return results

    def _default_agent_sources(self) -> tuple[dict[str, Path], str | None]:
        """Return ({filename: path}, reason) for ``DEFAULT_AGENTS_DIR``.

        ``reason`` is ``None`` when at least one file was found — the only case
        that guarantees the composed set is non-empty regardless of overrides
        or project-local agents — otherwise it explains why this layer was
        empty, for use as the skip reason when the whole composed set is empty.
        """
        if not DEFAULT_AGENTS_DIR.exists() or not DEFAULT_AGENTS_DIR.is_dir():
            return {}, "source directory missing"
        files = {p.name: p for p in sorted(DEFAULT_AGENTS_DIR.glob("*.md")) if p.is_file()}
        if not files:
            return {}, "no agent files in source"
        return files, None

    def _sync_directory(self, composed: dict[str, Path], target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        composed_names = set(composed.keys())

        for rel_name, src in composed.items():
            dst = target_dir / rel_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            _atomic_copy2(src, dst)

        for existing in target_dir.rglob("*.md"):
            if str(existing.relative_to(target_dir)) not in composed_names:
                try:
                    existing.unlink()
                    log.info("AgentFilesConfigurator: removed stale %s", existing)
                except OSError:
                    log.exception(
                        "AgentFilesConfigurator: failed to remove stale %s", existing
                    )

        log.info(
            "AgentFilesConfigurator: synced %d agent files into %s",
            len(composed), target_dir,
        )


class StopHookConfigurator(Configurator):
    """Ensures each active worktree's ``.claude/settings.json`` carries the Stop
    hook that runs ``stop-advance-action.py``.

    The advance-mode pipeline (compact / clear after major-phase transitions)
    requires this hook to be installed in every worktree. New workspaces get it
    via :mod:`routes.workspaces` at creation time; this configurator backfills
    existing worktrees so that toggling on the feature, or upgrading an older
    install, does not require manual settings-file edits.

    The existing settings file is preserved — only the missing Stop entry is
    appended. Worktrees without an existing ``settings.json`` are skipped (the
    workspace-creation path is responsible for the initial render).

    Like the agent sync, this configurator deliberately covers active worktrees
    only — the Stop hook drives the per-worktree advance pipeline.
    """

    OUTPUT_REL_PATH = Path(".claude") / "settings.json"
    HOOK_NAME = "stop-advance-action.py"

    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> list[dict]:
        stop_entry = self._build_stop_entry()
        results = []
        for working_dir in _active_worktree_paths(db, project_id):
            settings_path = Path(working_dir) / self.OUTPUT_REL_PATH
            if not settings_path.exists():
                log.info(
                    "StopHookConfigurator: %s missing, skipping (workspace bootstrap owns initial render)",
                    settings_path,
                )
                results.append(_skipped(str(settings_path), "settings.json missing"))
                continue
            results.append(self._merge_stop_hook(settings_path, stop_entry))
        return results

    def _build_stop_entry(self) -> dict:
        return {
            "hooks": [{
                "type": "command",
                "command": hook_command(self.HOOK_NAME),
            }]
        }

    def _merge_stop_hook(self, settings_path: Path, stop_entry: dict) -> dict:
        target = str(settings_path)
        try:
            existing = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, ValueError, OSError):
            log.warning(
                "StopHookConfigurator: %s is unreadable or invalid JSON, skipping",
                settings_path,
            )
            return _skipped(target, "unreadable or invalid JSON")

        if not isinstance(existing, dict):
            log.warning(
                "StopHookConfigurator: %s does not contain a JSON object, skipping",
                settings_path,
            )
            return _skipped(target, "settings root is not a JSON object")

        hooks_block = existing.setdefault("hooks", {})
        if not isinstance(hooks_block, dict):
            log.warning(
                "StopHookConfigurator: %s has non-object 'hooks' field, skipping",
                settings_path,
            )
            return _skipped(target, "'hooks' field is not an object")

        stop_entries = hooks_block.setdefault("Stop", [])
        if not isinstance(stop_entries, list):
            log.warning(
                "StopHookConfigurator: %s has non-array 'hooks.Stop' field, skipping",
                settings_path,
            )
            return _skipped(target, "'hooks.Stop' field is not an array")

        if self._has_equivalent_entry(stop_entries, stop_entry):
            log.debug(
                "StopHookConfigurator: %s already has the stop-advance-action hook",
                settings_path,
            )
            return _rendered(target)

        stop_entries.append(stop_entry)
        _atomic_write_text(settings_path, json.dumps(existing, indent=2))
        log.info("StopHookConfigurator: added Stop hook to %s", settings_path)
        return _rendered(target)

    def _has_equivalent_entry(self, existing_entries: list, candidate: dict) -> bool:
        candidate_commands = self._extract_commands(candidate)
        for entry in existing_entries:
            if not isinstance(entry, dict):
                continue
            if self._extract_commands(entry) == candidate_commands:
                return True
        return False

    def _extract_commands(self, entry: dict) -> set[str]:
        hooks = entry.get("hooks", [])
        if not isinstance(hooks, list):
            return set()
        return {
            h.get("command", "")
            for h in hooks
            if isinstance(h, dict) and h.get("command")
        }


class ConfiguratorChain:
    """Runs all registered configurators in order. Failures in one do not abort the chain
    — log and continue, so a single broken configurator can't block project saves."""

    def __init__(self, configurators: list[Configurator] | None = None):
        self._configurators = configurators or [
            SkillConfigurator(),
            AgentFilesConfigurator(),
            StopHookConfigurator(),
        ]

    def run(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> list[dict]:
        """Run every configurator and return the aggregated result entries.

        A configurator that raises contributes a single ``failed`` entry keyed
        by its class name; the chain still runs the remaining configurators.
        """
        results: list[dict] = []
        for cfg in self._configurators:
            try:
                results.extend(cfg.configure(db, project_id, project_path))
            except Exception as exc:
                log.exception(
                    "Configurator %s failed for project %s", type(cfg).__name__, project_id
                )
                results.append({
                    "target": type(cfg).__name__,
                    "action": "failed",
                    "reason": str(exc),
                })
        return results

    def run_for_workspace(
        self, db: sqlite3.Connection, project: sqlite3.Row, ws: sqlite3.Row
    ) -> list[dict]:
        """Re-render the workspace-scoped artifacts for a single worktree.

        Narrow counterpart to :meth:`run`: only configurators whose output
        varies per workspace (SKILL.md) do work here. Used when a single
        workspace's mode changes, so sibling worktrees are left untouched.
        """
        results: list[dict] = []
        for cfg in self._configurators:
            try:
                results.extend(cfg.configure_workspace(db, project, ws))
            except Exception as exc:
                log.exception(
                    "Configurator %s failed for workspace %s", type(cfg).__name__, ws["id"]
                )
                results.append({
                    "target": type(cfg).__name__,
                    "action": "failed",
                    "reason": str(exc),
                })
        return results

    @classmethod
    def default(cls) -> "ConfiguratorChain":
        return cls()


def rerender_all_projects(db: sqlite3.Connection) -> list[dict]:
    """Re-render every registered project's payload from current DB state.

    Used by the device-scope phase-settings save, the module-toggle save, and
    startup — each of which changes config that affects every project's render.
    Per-project failures are logged and do not abort the sweep. Returns the
    aggregated non-rendered result entries (skipped/failed) so callers can
    surface them as configurator warnings.
    """
    chain = ConfiguratorChain.default()
    warnings: list[dict] = []
    for project_row in db.execute("SELECT id, path FROM projects").fetchall():
        try:
            results = chain.run(db, project_row["id"], Path(project_row["path"]))
            warnings.extend(r for r in results if r["action"] != "rendered")
        except Exception:
            log.exception(
                "Configurator chain failed for project %s; SKILL.md may be stale",
                project_row["id"],
            )
    return warnings
