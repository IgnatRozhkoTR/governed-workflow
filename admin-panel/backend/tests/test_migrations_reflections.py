"""Tests for migration 0027_reflections: schema, constraints, and index."""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Fixture: isolated SQLite DB with minimal schema to run the migration against
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path):
    """Bare SQLite DB with only the workspaces table (prereq for FK)."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            registered TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(id),
            branch TEXT NOT NULL,
            sanitized_branch TEXT NOT NULL,
            working_dir TEXT NOT NULL,
            created TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            phase TEXT NOT NULL DEFAULT '0',
            scope_json TEXT NOT NULL DEFAULT '{}',
            plan_json TEXT NOT NULL DEFAULT '{}',
            source_branch TEXT NOT NULL DEFAULT 'main'
        )
    """)
    conn.commit()
    return conn


def _apply_migration(conn: sqlite3.Connection) -> None:
    """Load and execute the reflections migration against *conn*."""
    import yoyo as _yoyo

    captured: dict = {}
    original_step = _yoyo.step

    def _stub_step(fn_or_sql, *args, **kwargs):
        if callable(fn_or_sql):
            captured.setdefault("steps", []).append(fn_or_sql)
        else:
            captured.setdefault("sql_steps", []).append(fn_or_sql)

    _yoyo.step = _stub_step
    try:
        module_name = "migration_0027_reflections"
        if module_name in sys.modules:
            del sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(
            module_name,
            str(MIGRATIONS_DIR / "0027_reflections.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step

    # SQL steps collected in stub — execute each directly
    for sql in captured.get("sql_steps", []):
        conn.executescript(sql)
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReflectionsMigration:
    def test_reflections_table_exists_after_migration(self, fresh_db):
        _apply_migration(fresh_db)

        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reflections'"
        ).fetchone()

        assert row is not None
        assert row["name"] == "reflections"

    def test_reflections_columns_match_schema(self, fresh_db):
        _apply_migration(fresh_db)

        columns = {
            row["name"]: row
            for row in fresh_db.execute("PRAGMA table_info(reflections)").fetchall()
        }

        assert "id" in columns
        assert "workspace_id" in columns
        assert "content_md" in columns
        assert "summary" in columns
        assert "session_id" in columns
        assert "created_at" in columns
        assert columns["id"]["pk"] == 1

    def test_reflections_fk_cascade_on_workspace_delete(self, fresh_db):
        _apply_migration(fresh_db)
        fresh_db.execute("PRAGMA foreign_keys = ON")

        fresh_db.execute(
            "INSERT INTO projects (id, name, path, registered) VALUES ('p1', 'P', '/p', '2024-01-01')"
        )
        fresh_db.execute(
            "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, created) "
            "VALUES ('p1', 'main', 'main', '/p', '2024-01-01')"
        )
        ws_id = fresh_db.execute("SELECT last_insert_rowid()").fetchone()[0]
        fresh_db.execute(
            "INSERT INTO reflections (workspace_id, content_md, summary, created_at) "
            "VALUES (?, 'md', 'sum', '2024-01-01')",
            (ws_id,),
        )
        fresh_db.commit()

        count_before = fresh_db.execute(
            "SELECT COUNT(*) FROM reflections WHERE workspace_id = ?", (ws_id,)
        ).fetchone()[0]
        assert count_before == 1

        fresh_db.execute("DELETE FROM workspaces WHERE id = ?", (ws_id,))
        fresh_db.commit()

        count_after = fresh_db.execute(
            "SELECT COUNT(*) FROM reflections WHERE workspace_id = ?", (ws_id,)
        ).fetchone()[0]
        assert count_after == 0

    def test_reflections_index_exists(self, fresh_db):
        _apply_migration(fresh_db)

        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_reflections_workspace'"
        ).fetchone()

        assert row is not None
        assert row["name"] == "idx_reflections_workspace"
