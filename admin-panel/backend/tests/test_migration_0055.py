"""Tests for migration 0055_yolo_mode_default.

The session database replays every migration, so it shows the fresh-install
result. A hand-built pre-0055 schema covers an existing install and re-running
the step on it.
"""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "0055_yolo_mode_default.py"

_PRE_0055_SCHEMA = """
CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL);
INSERT INTO projects (id, name, path) VALUES ('existing', 'Existing', '/tmp/existing');
"""


def _load_steps():
    import yoyo

    captured = []
    original_step = yoyo.step
    yoyo.step = lambda apply, rollback=None, **kwargs: captured.append((apply, rollback))
    try:
        spec = importlib.util.spec_from_file_location("migration_0055_yolo_mode_default", MIGRATION_PATH)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    finally:
        yoyo.step = original_step
    return captured[0]


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def pre_0055_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_PRE_0055_SCHEMA)
    yield conn
    conn.close()


def test_fresh_install_has_yolo_mode_default_column_defaulting_to_zero(setup_db):
    conn = sqlite3.connect(str(setup_db))
    try:
        column = {row[1]: row for row in conn.execute("PRAGMA table_info(projects)")}["yolo_mode_default"]
        assert column[2] == "INTEGER"
        assert column[3] == 1
        assert column[4] == "0"
    finally:
        conn.close()


def test_apply_adds_column_and_existing_projects_default_to_zero(pre_0055_db):
    apply_step, _ = _load_steps()

    apply_step(pre_0055_db)

    assert "yolo_mode_default" in _columns(pre_0055_db, "projects")
    assert pre_0055_db.execute("SELECT yolo_mode_default FROM projects").fetchone()[0] == 0


def test_apply_twice_is_a_no_op(pre_0055_db):
    apply_step, _ = _load_steps()
    apply_step(pre_0055_db)
    pre_0055_db.execute("UPDATE projects SET yolo_mode_default = 1")

    apply_step(pre_0055_db)

    assert pre_0055_db.execute("SELECT yolo_mode_default FROM projects").fetchone()[0] == 1


def test_rollback_drops_column(pre_0055_db):
    apply_step, rollback_step = _load_steps()
    apply_step(pre_0055_db)

    rollback_step(pre_0055_db)

    assert "yolo_mode_default" not in _columns(pre_0055_db, "projects")


def test_rollback_twice_is_a_no_op(pre_0055_db):
    apply_step, rollback_step = _load_steps()
    apply_step(pre_0055_db)
    rollback_step(pre_0055_db)

    rollback_step(pre_0055_db)

    assert _columns(pre_0055_db, "projects") == {"id", "name", "path"}
