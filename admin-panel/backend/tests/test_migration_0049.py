"""Tests for migration 0049_fast_mode_includes_reflection.

Verifies the legacy workspace-scope 5.1/5.2 disable rows are removed for
fast-mode workspaces (forward) and can be restored (backward).
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _load_migration_module():
    """Load the 0049 module without invoking yoyo.step side effects."""
    import yoyo as _yoyo

    original_step = _yoyo.step
    _yoyo.step = lambda *args, **kwargs: None
    try:
        module_name = "migration_0049_fast_mode_includes_reflection"
        if module_name in sys.modules:
            del sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(
            module_name, str(MIGRATIONS_DIR / "0049_fast_mode_includes_reflection.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step
    return mod


@pytest.fixture
def workspaces_and_settings_db(tmp_path):
    """A workspaces + phase_settings pair seeded with a fast and a standard workspace."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_mode TEXT NOT NULL DEFAULT 'standard'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE phase_settings (
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL DEFAULT '',
            phase_id TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (scope_type, scope_id, phase_id)
        )
        """
    )
    return conn


def _seed_fast_workspace_with_legacy_rows(db, workspace_id):
    db.execute(
        "INSERT INTO workspaces (id, workflow_mode) VALUES (?, 'fast')", (workspace_id,)
    )
    for phase_id in ("1.3", "1.4", "3.x.1", "3.x.2", "3.x.3", "4.0", "5.1", "5.2"):
        db.execute(
            "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled) "
            "VALUES ('workspace', ?, ?, 0)",
            (str(workspace_id), phase_id),
        )


def test_forward_removes_legacy_reflection_rows_for_fast_workspace(workspaces_and_settings_db):
    _seed_fast_workspace_with_legacy_rows(workspaces_and_settings_db, 1)
    workspaces_and_settings_db.commit()

    mod = _load_migration_module()
    mod.remove_fast_mode_reflection_disable_rows(workspaces_and_settings_db)
    workspaces_and_settings_db.commit()

    remaining = {
        row["phase_id"]
        for row in workspaces_and_settings_db.execute(
            "SELECT phase_id FROM phase_settings WHERE scope_type = 'workspace' AND scope_id = '1'"
        ).fetchall()
    }
    assert remaining == {"1.3", "1.4", "3.x.1", "3.x.2", "3.x.3", "4.0"}


def test_forward_leaves_standard_workspace_rows_untouched(workspaces_and_settings_db):
    workspaces_and_settings_db.execute(
        "INSERT INTO workspaces (id, workflow_mode) VALUES (2, 'standard')"
    )
    workspaces_and_settings_db.execute(
        "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled) "
        "VALUES ('workspace', '2', '5.1', 0)"
    )
    workspaces_and_settings_db.commit()

    mod = _load_migration_module()
    mod.remove_fast_mode_reflection_disable_rows(workspaces_and_settings_db)
    workspaces_and_settings_db.commit()

    remaining = workspaces_and_settings_db.execute(
        "SELECT phase_id FROM phase_settings WHERE scope_type = 'workspace' AND scope_id = '2'"
    ).fetchall()
    assert [row["phase_id"] for row in remaining] == ["5.1"]


def test_forward_is_idempotent_with_no_fast_workspaces(workspaces_and_settings_db):
    workspaces_and_settings_db.commit()

    mod = _load_migration_module()
    mod.remove_fast_mode_reflection_disable_rows(workspaces_and_settings_db)
    workspaces_and_settings_db.commit()

    count = workspaces_and_settings_db.execute(
        "SELECT COUNT(*) FROM phase_settings"
    ).fetchone()[0]
    assert count == 0


def test_backward_restores_disable_rows_for_fast_workspace(workspaces_and_settings_db):
    workspaces_and_settings_db.execute(
        "INSERT INTO workspaces (id, workflow_mode) VALUES (3, 'fast')"
    )
    workspaces_and_settings_db.commit()

    mod = _load_migration_module()
    mod.restore_fast_mode_reflection_disable_rows(workspaces_and_settings_db)
    workspaces_and_settings_db.commit()

    rows = {
        row["phase_id"]: row["enabled"]
        for row in workspaces_and_settings_db.execute(
            "SELECT phase_id, enabled FROM phase_settings WHERE scope_type = 'workspace' AND scope_id = '3'"
        ).fetchall()
    }
    assert rows == {"5.1": 0, "5.2": 0}


def test_backward_is_idempotent(workspaces_and_settings_db):
    workspaces_and_settings_db.execute(
        "INSERT INTO workspaces (id, workflow_mode) VALUES (4, 'fast')"
    )
    workspaces_and_settings_db.commit()

    mod = _load_migration_module()
    mod.restore_fast_mode_reflection_disable_rows(workspaces_and_settings_db)
    mod.restore_fast_mode_reflection_disable_rows(workspaces_and_settings_db)
    workspaces_and_settings_db.commit()

    count = workspaces_and_settings_db.execute(
        "SELECT COUNT(*) FROM phase_settings WHERE scope_type = 'workspace' AND scope_id = '4'"
    ).fetchone()[0]
    assert count == 2
