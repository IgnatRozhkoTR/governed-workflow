"""Configurator chain — renders project-level files from current workspace settings.

Triggered explicitly from mutator endpoints (workspace creation, project settings save,
work-mode assignment, module toggle, etc.). No event bus.
"""

from abc import ABC, abstractmethod
from pathlib import Path
import logging
import sqlite3

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


class ConfiguratorChain:
    """Runs all registered configurators in order. Failures in one do not abort the chain
    — log and continue, so a single broken configurator can't block project saves."""

    def __init__(self, configurators: list[Configurator] | None = None):
        self._configurators = configurators or [SkillConfigurator()]

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
