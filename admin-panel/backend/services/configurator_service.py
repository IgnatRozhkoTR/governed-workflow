"""Configurator chain — renders project-level files from current workspace settings.

Triggered explicitly from mutator endpoints (workspace creation, project settings save,
work-mode assignment, module toggle, etc.). No event bus.
"""

import json
import logging
import shutil
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

from core.paths import DEFAULT_AGENTS_DIR, hook_command

log = logging.getLogger(__name__)


class Configurator(ABC):
    """Renders one piece of project/worktree configuration from current DB state."""

    @abstractmethod
    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> None:
        """Apply this configurator for the given project. Idempotent — safe to re-run."""


class SkillConfigurator(Configurator):
    """Renders SKILL.md from SKILL.md.template + each enabled phase's description_for_skill()."""

    TEMPLATE_REL_PATH = "claude/skills/governed-workflow/SKILL.md.template"
    OUTPUT_REL_PATH = ".claude/skills/governed-workflow/SKILL.md"
    PLACEHOLDER = "{{PHASES}}"

    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> None:
        template_path = project_path / self.TEMPLATE_REL_PATH
        if not template_path.exists():
            log.warning("SkillConfigurator: template missing at %s, skipping", template_path)
            return

        template = template_path.read_text()
        if self.PLACEHOLDER not in template:
            log.warning(
                "SkillConfigurator: template at %s lacks %s placeholder, skipping",
                template_path,
                self.PLACEHOLDER,
            )
            return

        phase_block = self._build_phase_block(db, project_id)
        rendered = template.replace(self.PLACEHOLDER, phase_block)

        # Write to project-level path (so newly-created worktrees inherit via install merge).
        project_output = project_path / self.OUTPUT_REL_PATH
        self._write(project_output, rendered)

        # Write to each active worktree.
        for working_dir in self._list_active_worktree_paths(db, project_id):
            worktree_output = Path(working_dir) / self.OUTPUT_REL_PATH
            self._write(worktree_output, rendered)

    def _build_phase_block(self, db: sqlite3.Connection, project_id: int) -> str:
        """Concatenate each enabled phase's description_for_skill() in resolved order.

        Uses basic-mode baseline + device/project scope overrides via
        phase_resolver.resolve_for_project. Skips phases without a registered
        instance or with an empty description.
        """
        from advance.phases import get_phase  # avoid circular import at module load
        from services import phase_resolver

        phase_ids = phase_resolver.resolve_for_project(db, project_id)
        blocks = []
        for pid in phase_ids:
            phase = get_phase(pid)
            if phase is None:
                continue
            block = phase.description_for_skill().strip()
            if block:
                blocks.append(block)
        return "\n\n---\n\n".join(blocks)

    def _list_active_worktree_paths(self, db: sqlite3.Connection, project_id: int) -> list[str]:
        cur = db.execute(
            "SELECT working_dir FROM workspaces WHERE project_id = ? AND status = 'active'",
            (project_id,),
        )
        return [row[0] for row in cur.fetchall() if row[0]]

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        log.info("SkillConfigurator: wrote %s (%d bytes)", path, len(content))


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
    """

    OUTPUT_REL_DIR = Path(".claude") / "agents"

    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> None:
        source_dir = DEFAULT_AGENTS_DIR
        if not source_dir.exists() or not source_dir.is_dir():
            log.warning(
                "AgentFilesConfigurator: source %s missing, skipping",
                source_dir,
            )
            return

        source_agents = sorted(p for p in source_dir.glob("*.md") if p.is_file())
        if not source_agents:
            log.warning(
                "AgentFilesConfigurator: no *.md files in %s, skipping",
                source_dir,
            )
            return

        for working_dir in self._list_active_worktree_paths(db, project_id):
            target_dir = Path(working_dir) / self.OUTPUT_REL_DIR
            self._sync_directory(source_agents, target_dir)

    def _sync_directory(self, source_agents: list[Path], target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        source_names = {p.name for p in source_agents}

        for src in source_agents:
            dst = target_dir / src.name
            shutil.copy2(src, dst)

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

    def _list_active_worktree_paths(self, db: sqlite3.Connection, project_id: int) -> list[str]:
        cur = db.execute(
            "SELECT working_dir FROM workspaces WHERE project_id = ? AND status = 'active'",
            (project_id,),
        )
        return [row[0] for row in cur.fetchall() if row[0]]


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
    """

    OUTPUT_REL_PATH = Path(".claude") / "settings.json"
    HOOK_NAME = "stop-advance-action.py"

    def configure(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> None:
        stop_entry = self._build_stop_entry()
        for working_dir in self._list_active_worktree_paths(db, project_id):
            settings_path = Path(working_dir) / self.OUTPUT_REL_PATH
            if not settings_path.exists():
                log.info(
                    "StopHookConfigurator: %s missing, skipping (workspace bootstrap owns initial render)",
                    settings_path,
                )
                continue
            self._merge_stop_hook(settings_path, stop_entry)

    def _build_stop_entry(self) -> dict:
        return {
            "hooks": [{
                "type": "command",
                "command": hook_command(self.HOOK_NAME),
            }]
        }

    def _merge_stop_hook(self, settings_path: Path, stop_entry: dict) -> None:
        try:
            existing = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, ValueError, OSError):
            log.warning(
                "StopHookConfigurator: %s is unreadable or invalid JSON, skipping",
                settings_path,
            )
            return

        if not isinstance(existing, dict):
            log.warning(
                "StopHookConfigurator: %s does not contain a JSON object, skipping",
                settings_path,
            )
            return

        hooks_block = existing.setdefault("hooks", {})
        if not isinstance(hooks_block, dict):
            log.warning(
                "StopHookConfigurator: %s has non-object 'hooks' field, skipping",
                settings_path,
            )
            return

        stop_entries = hooks_block.setdefault("Stop", [])
        if not isinstance(stop_entries, list):
            log.warning(
                "StopHookConfigurator: %s has non-array 'hooks.Stop' field, skipping",
                settings_path,
            )
            return

        if self._has_equivalent_entry(stop_entries, stop_entry):
            log.debug(
                "StopHookConfigurator: %s already has the stop-advance-action hook",
                settings_path,
            )
            return

        stop_entries.append(stop_entry)
        settings_path.write_text(json.dumps(existing, indent=2))
        log.info("StopHookConfigurator: added Stop hook to %s", settings_path)

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

    def _list_active_worktree_paths(self, db: sqlite3.Connection, project_id: int) -> list[str]:
        cur = db.execute(
            "SELECT working_dir FROM workspaces WHERE project_id = ? AND status = 'active'",
            (project_id,),
        )
        return [row[0] for row in cur.fetchall() if row[0]]


class ConfiguratorChain:
    """Runs all registered configurators in order. Failures in one do not abort the chain
    — log and continue, so a single broken configurator can't block project saves."""

    def __init__(self, configurators: list[Configurator] | None = None):
        self._configurators = configurators or [
            SkillConfigurator(),
            AgentFilesConfigurator(),
            StopHookConfigurator(),
        ]

    def run(self, db: sqlite3.Connection, project_id: int, project_path: Path) -> None:
        for cfg in self._configurators:
            try:
                cfg.configure(db, project_id, project_path)
            except Exception:
                log.exception(
                    "Configurator %s failed for project %s", type(cfg).__name__, project_id
                )

    @classmethod
    def default(cls) -> "ConfiguratorChain":
        return cls()
