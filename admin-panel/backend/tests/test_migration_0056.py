"""Tests for migration 0056_drop_simple_planning_and_review_issues.

The session database replays every migration, so it shows the fresh-install
result. A hand-built pre-0056 schema covers an existing install and re-running
the step on it.
"""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "migrations" / "0056_drop_simple_planning_and_review_issues.py"
)

_PRE_0056_SCHEMA = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    simple_planning INTEGER NOT NULL DEFAULT 0, fast_mode_default INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE workspaces (id INTEGER PRIMARY KEY, project_id TEXT);
CREATE TABLE review_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    description TEXT NOT NULL
);
INSERT INTO projects (id, name, simple_planning, fast_mode_default) VALUES
    ('simple', 'Simple', 1, 0),
    ('full', 'Full', 0, 1);
INSERT INTO workspaces (id, project_id) VALUES (1, 'simple');
INSERT INTO review_issues (workspace_id, description) VALUES (1, 'stale finding');
"""


def _load_apply_step():
    import yoyo

    captured = []
    original_step = yoyo.step
    yoyo.step = lambda apply, rollback=None, **kwargs: captured.append(apply)
    try:
        spec = importlib.util.spec_from_file_location(
            "migration_0056_drop_simple_planning_and_review_issues", MIGRATION_PATH
        )
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    finally:
        yoyo.step = original_step
    return captured[0]


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@pytest.fixture
def pre_0056_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_PRE_0056_SCHEMA)
    yield conn
    conn.close()


def test_fresh_install_has_no_simple_planning_or_review_issues(setup_db):
    conn = sqlite3.connect(str(setup_db))
    try:
        assert "simple_planning" not in _columns(conn, "projects")
        assert "review_issues" not in _tables(conn)
    finally:
        conn.close()


def test_apply_drops_simple_planning_and_keeps_other_project_data(pre_0056_db):
    _load_apply_step()(pre_0056_db)

    assert _columns(pre_0056_db, "projects") == {"id", "name", "fast_mode_default"}
    rows = pre_0056_db.execute("SELECT id, name, fast_mode_default FROM projects ORDER BY id").fetchall()
    assert rows == [("full", "Full", 1), ("simple", "Simple", 0)]


def test_apply_drops_review_issues_and_keeps_workspaces(pre_0056_db):
    _load_apply_step()(pre_0056_db)

    assert "review_issues" not in _tables(pre_0056_db)
    assert pre_0056_db.execute("SELECT id, project_id FROM workspaces").fetchall() == [(1, "simple")]


def test_apply_twice_is_a_no_op(pre_0056_db):
    apply_step = _load_apply_step()
    apply_step(pre_0056_db)

    apply_step(pre_0056_db)

    assert _columns(pre_0056_db, "projects") == {"id", "name", "fast_mode_default"}
    assert "review_issues" not in _tables(pre_0056_db)
