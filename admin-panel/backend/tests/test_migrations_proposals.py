"""Tests for migration 0032_drop_proposals_type_check.

Verifies that the rebuild idiom removes the CHECK constraint on proposals.type
while preserving all existing data and indexes, and that after migration the
table accepts INSERT with a hypothetical future type not in the current enum.
"""
import importlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


@pytest.fixture
def pre_migration_db(tmp_path):
    """SQLite DB with the original proposals table including the type CHECK constraint."""
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
            created TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK (type IN (
                'memory_write','memory_delete',
                'rule_new','rule_update',
                'agent_new','agent_update',
                'skill_new','skill_update',
                'workflow_improvement'
            )),
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                'pending','approved','rejected','executed','failed'
            )),
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            origin TEXT NOT NULL DEFAULT 'agent',
            workspace_id INTEGER REFERENCES workspaces(id) ON DELETE SET NULL,
            project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
            reason TEXT,
            result_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            reviewed_at TEXT,
            executed_at TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_proposals_status_created
        ON proposals(status, created_at DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_proposals_project_status
        ON proposals(project_id, status)
    """)
    conn.commit()
    return conn


def _apply_migration(conn: sqlite3.Connection) -> None:
    """Load and execute migration 0032 step-by-step against *conn*."""
    import yoyo as _yoyo

    captured: dict = {"sql_steps": []}
    original_step = _yoyo.step

    def _stub_step(fn_or_sql, *args, **kwargs):
        if isinstance(fn_or_sql, str):
            captured["sql_steps"].append(fn_or_sql)

    _yoyo.step = _stub_step
    try:
        module_name = "migration_0032_drop_proposals_type_check"
        if module_name in sys.modules:
            del sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(
            module_name,
            str(MIGRATIONS_DIR / "0032_drop_proposals_type_check.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step

    for sql in captured["sql_steps"]:
        conn.execute(sql)
    conn.commit()


class TestDropProposalsTypeCheck:
    def test_proposals_table_exists_after_migration(self, pre_migration_db):
        _apply_migration(pre_migration_db)

        row = pre_migration_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='proposals'"
        ).fetchone()

        assert row is not None

    def test_migration_preserves_existing_rows(self, pre_migration_db):
        pre_migration_db.execute(
            "INSERT INTO proposals (type, title, origin, created_at) "
            "VALUES ('memory_write', 'Existing row', 'agent', '2024-01-01T00:00:00')"
        )
        pre_migration_db.commit()

        _apply_migration(pre_migration_db)

        rows = pre_migration_db.execute("SELECT * FROM proposals").fetchall()
        assert len(rows) == 1
        assert rows[0]["type"] == "memory_write"
        assert rows[0]["title"] == "Existing row"

    def test_future_type_is_accepted_after_migration(self, pre_migration_db):
        _apply_migration(pre_migration_db)

        pre_migration_db.execute(
            "INSERT INTO proposals (type, title, origin, created_at) "
            "VALUES ('hypothetical_future_type', 'Future proposal', 'agent', '2025-01-01T00:00:00')"
        )
        pre_migration_db.commit()

        row = pre_migration_db.execute(
            "SELECT type FROM proposals WHERE title = 'Future proposal'"
        ).fetchone()

        assert row is not None
        assert row["type"] == "hypothetical_future_type"

    def test_type_check_constraint_is_absent_after_migration(self, pre_migration_db):
        _apply_migration(pre_migration_db)

        ddl = pre_migration_db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='proposals'"
        ).fetchone()["sql"]

        assert "CHECK (type IN" not in ddl

    def test_status_check_constraint_is_preserved_after_migration(self, pre_migration_db):
        _apply_migration(pre_migration_db)

        ddl = pre_migration_db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='proposals'"
        ).fetchone()["sql"]

        assert "CHECK (status IN" in ddl

    def test_indexes_exist_after_migration(self, pre_migration_db):
        _apply_migration(pre_migration_db)

        indexes = {
            row["name"]
            for row in pre_migration_db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='proposals'"
            ).fetchall()
        }

        assert "idx_proposals_status_created" in indexes
        assert "idx_proposals_project_status" in indexes

    def test_all_columns_preserved_after_migration(self, pre_migration_db):
        _apply_migration(pre_migration_db)

        columns = {
            row["name"]
            for row in pre_migration_db.execute("PRAGMA table_info(proposals)").fetchall()
        }

        expected = {
            "id", "type", "status", "title", "body", "payload_json",
            "origin", "workspace_id", "project_id", "reason", "result_json",
            "created_at", "reviewed_at", "executed_at",
        }
        assert expected.issubset(columns)
