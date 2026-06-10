#!/usr/bin/env python3
"""One-shot migration: run the full configurator chain for every registered project.

Renders each project's payload — SKILL.md, the mirrored agent files, and the
Stop hook in active worktree settings — from current DB state.

Run from anywhere:
    python3 admin-panel/backend/scripts/migrate_skill_md.py

Exit 0 if all projects succeeded, 1 if any failed.
"""
import logging
import sys
from pathlib import Path

# Ensure the backend package root is importable regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from advance.phases import register_module_phases_from_disk
from core.db import get_db
from services.configurator_service import ConfiguratorChain

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    register_module_phases_from_disk()

    db = get_db()
    try:
        rows = db.execute("SELECT id, path FROM projects").fetchall()
    finally:
        db.close()

    if not rows:
        log.info("No projects found in DB — nothing to do.")
        return 0

    log.info("Found %d project(s) to process.", len(rows))
    chain = ConfiguratorChain.default()
    failed = 0

    for row in rows:
        project_id = row["id"]
        project_path = Path(row["path"])
        log.info("Processing project id=%s path=%s", project_id, project_path)
        db = get_db()
        try:
            chain.run(db, project_id, project_path)
            log.info("  OK: project %s", project_id)
        except Exception:
            log.exception("  FAILED: project %s", project_id)
            failed += 1
        finally:
            db.close()

    log.info("Done. %d succeeded, %d failed.", len(rows) - failed, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
