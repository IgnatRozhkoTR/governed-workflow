#!/usr/bin/env python3
"""Regenerate the committed default SKILL.md from its template + current phase classes.

Renders the clean-default phase set (no DB overrides) into
``claude/skills/governed-workflow/SKILL.md`` so the shipped payload always
matches the phase definitions in ``advance/phases``.

Run from anywhere:
    python3 admin-panel/backend/scripts/render_default_skill.py

Exit 0 on success, 1 if the default template is missing or lacks placeholders.
"""
import logging
import sqlite3
import sys
from pathlib import Path

# Ensure the backend package root is importable regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from advance.phases import register_module_phases_from_disk
from core.paths import DEFAULT_SKILLS_DIR
from services import phase_resolver
from services.configurator_service import SkillConfigurator

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

_TEMPLATE_PATH = DEFAULT_SKILLS_DIR / "governed-workflow" / "SKILL.md.template"
_OUTPUT_PATH = DEFAULT_SKILLS_DIR / "governed-workflow" / "SKILL.md"


def _clean_default_phase_ids() -> list[str]:
    """Resolve the phase id list with no project/device overrides applied."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE phase_settings ("
        "scope_type TEXT, scope_id TEXT, phase_id TEXT, enabled INTEGER)"
    )
    try:
        return phase_resolver.resolve_for_project(db, None, include_templated=True)
    finally:
        db.close()


def main() -> int:
    register_module_phases_from_disk()

    if not _TEMPLATE_PATH.exists():
        log.error("Default template missing at %s", _TEMPLATE_PATH)
        return 1

    template = _TEMPLATE_PATH.read_text()
    if SkillConfigurator.PLACEHOLDER_PHASES not in template:
        log.error("Default template at %s lacks %s", _TEMPLATE_PATH, SkillConfigurator.PLACEHOLDER_PHASES)
        return 1

    phase_ids = _clean_default_phase_ids()
    rendered = SkillConfigurator.render(template, phase_ids)
    _OUTPUT_PATH.write_text(rendered)
    log.info("Wrote %s (%d bytes, %d phases)", _OUTPUT_PATH, len(rendered), len(phase_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
