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

from core.paths import DEFAULT_AGENTS_DIR, DEFAULT_SKILLS_DIR, hook_command

log = logging.getLogger(__name__)


def _on_off(flag: bool) -> str:
    return "ON" if flag else "OFF"


def _active_worktree_paths(db: sqlite3.Connection, project_id: int) -> list[str]:
    cur = db.execute(
        "SELECT working_dir FROM workspaces WHERE project_id = ? AND status = 'active'",
        (project_id,),
    )
    return [row[0] for row in cur.fetchall() if row[0]]


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


class SkillConfigurator(Configurator):
    """Renders SKILL.md from SKILL.md.template + each enabled phase's description_for_skill().

    Unlike the other configurators this also writes the project root so a fresh
    install seeds the canonical SKILL.md before any worktree exists; active
    worktrees additionally receive their own copy.
    """

    TEMPLATE_REL_PATH = ".claude/skills/governed-workflow/SKILL.md.template"
    OUTPUT_REL_PATH = ".claude/skills/governed-workflow/SKILL.md"
    DEFAULT_TEMPLATE_PATH = DEFAULT_SKILLS_DIR / "governed-workflow" / "SKILL.md.template"
    PLACEHOLDER_PHASES = "{{PHASES}}"
    PLACEHOLDER_PHASE_MAP = "{{PHASE_MAP}}"

    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> list[dict]:
        template_path = self._resolve_template_path(project_path)
        if template_path is None:
            log.warning(
                "SkillConfigurator: template missing in project %s and default %s, skipping",
                project_path,
                self.DEFAULT_TEMPLATE_PATH,
            )
            return [_skipped("SKILL.md", "template missing")]

        template = template_path.read_text()
        if self.PLACEHOLDER_PHASES not in template:
            log.warning(
                "SkillConfigurator: template at %s lacks %s placeholder, skipping",
                template_path,
                self.PLACEHOLDER_PHASES,
            )
            return [_skipped("SKILL.md", "template missing placeholder")]

        phase_ids = self._resolve_phase_ids(db, project_id)
        rendered = self.render(template, phase_ids)

        results = [self._write_target(project_path / self.OUTPUT_REL_PATH, rendered)]
        for working_dir in _active_worktree_paths(db, project_id):
            results.append(
                self._write_target(Path(working_dir) / self.OUTPUT_REL_PATH, rendered)
            )
        return results

    def _resolve_template_path(self, project_path: Path) -> Path | None:
        """Project-level template if present, else the shipped default, else None."""
        project_template = project_path / self.TEMPLATE_REL_PATH
        if project_template.exists():
            return project_template
        if self.DEFAULT_TEMPLATE_PATH.exists():
            return self.DEFAULT_TEMPLATE_PATH
        return None

    @classmethod
    def render(cls, template: str, phase_ids: list[str]) -> str:
        """Substitute the {{PHASES}} and {{PHASE_MAP}} placeholders for *phase_ids*."""
        return template.replace(
            cls.PLACEHOLDER_PHASES, cls._build_phase_block(phase_ids)
        ).replace(
            cls.PLACEHOLDER_PHASE_MAP, cls._build_phase_map(phase_ids)
        )

    def _resolve_phase_ids(self, db: sqlite3.Connection, project_id: int) -> list[str]:
        """Resolved phase ids for the project, including templated execution rows."""
        from services import phase_resolver

        return phase_resolver.resolve_for_project(db, project_id, include_templated=True)

    @staticmethod
    def _build_phase_block(phase_ids: list[str]) -> str:
        """Concatenate each enabled phase's description_for_skill() in resolved order.

        Skips phases without a registered instance or with an empty description.
        """
        from advance.phases import get_phase  # avoid circular import at module load

        blocks = []
        for pid in phase_ids:
            phase = get_phase(pid)
            if phase is None:
                continue
            block = phase.description_for_skill().strip()
            if block:
                blocks.append(block)
        return "\n\n---\n\n".join(blocks)

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
    """Mirrors ``claude/agents/*.md`` from the governed-workflow install into every
    active worktree's ``.claude/agents/`` directory.

    Existing worktrees stay in lock-step with the canonical agent set. On each run
    every ``*.md`` from the source directory is copied (overwriting if present), and
    any ``*.md`` in the worktree's ``.claude/agents/`` that is no longer present in
    the source is removed — otherwise a renamed/retired agent (e.g. the collapsed
    ``logic-reviewer`` / ``security-reviewer``) would linger and continue to be
    advertised by Claude Code.

    The source directory is :data:`core.paths.DEFAULT_AGENTS_DIR`. If it does not
    exist (uninstalled / partial install), the configurator skips silently.

    This configurator deliberately covers active worktrees only — the project
    root is never an execution workspace, so its ``.claude/agents/`` does not
    need the canonical agent set.
    """

    OUTPUT_REL_DIR = Path(".claude") / "agents"

    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> list[dict]:
        source_dir = DEFAULT_AGENTS_DIR
        if not source_dir.exists() or not source_dir.is_dir():
            log.warning(
                "AgentFilesConfigurator: source %s missing, skipping",
                source_dir,
            )
            return [_skipped("agents", "source directory missing")]

        source_agents = sorted(p for p in source_dir.glob("*.md") if p.is_file())
        if not source_agents:
            log.warning(
                "AgentFilesConfigurator: no *.md files in %s, skipping",
                source_dir,
            )
            return [_skipped("agents", "no agent files in source")]

        results = []
        for working_dir in _active_worktree_paths(db, project_id):
            target_dir = Path(working_dir) / self.OUTPUT_REL_DIR
            self._sync_directory(source_agents, target_dir)
            results.append(_rendered(str(target_dir)))
        return results

    def _sync_directory(self, source_agents: list[Path], target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        source_names = {p.name for p in source_agents}

        for src in source_agents:
            _atomic_copy2(src, target_dir / src.name)

        for existing in target_dir.glob("*.md"):
            if existing.name not in source_names:
                try:
                    existing.unlink()
                    log.info("AgentFilesConfigurator: removed stale %s", existing)
                except OSError:
                    log.exception(
                        "AgentFilesConfigurator: failed to remove stale %s", existing
                    )

        log.info(
            "AgentFilesConfigurator: synced %d agent files into %s",
            len(source_agents), target_dir,
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

    @classmethod
    def default(cls) -> "ConfiguratorChain":
        return cls()
