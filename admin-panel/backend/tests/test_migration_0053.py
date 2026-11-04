"""Tests for migration 0053_multi_repo_projects.

Verifies the ``projects.project_type`` column and the ``project_repos``,
``workspace_repos``, and ``workspace_prs`` tables are created forward, that
re-applying is a no-op error-wise, and that rollback tears everything back
down.
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


def _load_migration_steps():
    """Capture every (apply, rollback) pair registered by the 0053 module.

    ``yoyo.step`` is replaced with a recorder instead of a no-op so this test
    can replay both directions of every step (raw-SQL strings and callables
    alike) against a plain sqlite3 connection, without needing a full yoyo
    backend.
    """
    import yoyo as _yoyo

    original_step = _yoyo.step
    captured = []

    def _stub_step(apply, rollback=None, **kwargs):
        captured.append((apply, rollback))

    _yoyo.step = _stub_step
    try:
        module_name = "migration_0053_multi_repo_projects"
        if module_name in sys.modules:
            del sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(
            module_name, str(MIGRATIONS_DIR / "0053_multi_repo_projects.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step
    return captured


def _run(step_item, conn):
    if callable(step_item):
        step_item(conn)
    else:
        conn.execute(step_item)
    conn.commit()


def apply_all(conn):
    for apply_step, _rollback in _load_migration_steps():
        _run(apply_step, conn)


def rollback_all(conn):
    for _apply, rollback in reversed(_load_migration_steps()):
        if rollback is not None:
            _run(rollback, conn)


def _table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _column_names(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


@pytest.fixture
def seeded_db(tmp_path):
    """Minimal projects + workspaces schema, mirroring the tables 0053 extends/references."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, "
        "registered TEXT NOT NULL)"
    )
    conn.execute("CREATE TABLE workspaces (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    conn.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES ('p1', 'P1', '/tmp/p1', '2026-01-01')"
    )
    conn.commit()
    yield conn
    conn.close()


def test_apply_adds_project_type_column_with_single_default(seeded_db):
    apply_all(seeded_db)

    assert "project_type" in _column_names(seeded_db, "projects")
    row = seeded_db.execute("SELECT project_type FROM projects WHERE id = 'p1'").fetchone()
    assert row["project_type"] == "single"


def test_apply_creates_registry_tables(seeded_db):
    apply_all(seeded_db)

    tables = _table_names(seeded_db)
    assert {"project_repos", "workspace_repos", "workspace_prs"} <= tables


def test_apply_project_repos_enforces_unique_rel_path_per_project(seeded_db):
    apply_all(seeded_db)

    seeded_db.execute(
        "INSERT INTO project_repos (project_id, rel_path, name, registered) "
        "VALUES ('p1', 'service-a', 'service-a', '2026-01-01')"
    )
    seeded_db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        seeded_db.execute(
            "INSERT INTO project_repos (project_id, rel_path, name, registered) "
            "VALUES ('p1', 'service-a', 'service-a-dup', '2026-01-01')"
        )


def test_apply_workspace_prs_allows_multiple_null_repo_id_rows(seeded_db):
    """SQLite treats NULLs as distinct, so no UNIQUE constraint blocks the upsert-in-code design."""
    apply_all(seeded_db)

    seeded_db.execute(
        "INSERT INTO workspaces (id) VALUES (1)"
    )
    seeded_db.execute(
        "INSERT INTO workspace_prs (workspace_id, repo_id, url, created) "
        "VALUES (1, NULL, 'https://example.com/pr/1', '2026-01-01')"
    )
    seeded_db.execute(
        "INSERT INTO workspace_prs (workspace_id, repo_id, url, created) "
        "VALUES (1, NULL, 'https://example.com/pr/2', '2026-01-01')"
    )
    seeded_db.commit()

    count = seeded_db.execute("SELECT COUNT(*) FROM workspace_prs WHERE workspace_id = 1").fetchone()[0]
    assert count == 2


def test_apply_is_idempotent(seeded_db):
    apply_all(seeded_db)
    apply_all(seeded_db)

    assert "project_type" in _column_names(seeded_db, "projects")
    assert {"project_repos", "workspace_repos", "workspace_prs"} <= _table_names(seeded_db)


def test_rollback_drops_tables_and_column(seeded_db):
    apply_all(seeded_db)

    rollback_all(seeded_db)

    assert "project_type" not in _column_names(seeded_db, "projects")
    tables = _table_names(seeded_db)
    assert "project_repos" not in tables
    assert "workspace_repos" not in tables
    assert "workspace_prs" not in tables


def test_rollback_is_idempotent(seeded_db):
    apply_all(seeded_db)
    rollback_all(seeded_db)
    rollback_all(seeded_db)

    assert "project_type" not in _column_names(seeded_db, "projects")
