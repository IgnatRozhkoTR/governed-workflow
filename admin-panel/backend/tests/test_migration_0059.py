"""Tests for migration 0059_annotations."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "0059_annotations.py"

_WORKSPACES_SCHEMA = "CREATE TABLE workspaces (id INTEGER PRIMARY KEY);"
_EXPECTED_COLUMNS = ["id", "workspace_id", "repo", "file_path", "line_start", "line_end", "text",
                     "author", "anchor_text", "base_commit", "created_at", "updated_at"]


def _load_steps():
    import yoyo

    captured = []
    original_step = yoyo.step
    yoyo.step = lambda apply, rollback=None, **kwargs: captured.append(apply)
    try:
        spec = importlib.util.spec_from_file_location("migration_0059", MIGRATION_PATH)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    finally:
        yoyo.step = original_step
    return captured


def _apply_all(conn):
    for sql in _load_steps():
        conn.execute(sql)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_WORKSPACES_SCHEMA)
    yield connection
    connection.close()


def _insert_annotation(conn, workspace_id=1):
    conn.execute(
        "INSERT INTO annotations (workspace_id, file_path, line_start, line_end, text, author, anchor_text) "
        "VALUES (?, 'a.py', 1, 1, 'note', 'agent', 'x')",
        (workspace_id,),
    )


def test_apply_should_create_annotations_table_with_expected_columns(conn):
    _apply_all(conn)

    columns = [row[1] for row in conn.execute("PRAGMA table_info(annotations)")]
    assert columns == _EXPECTED_COLUMNS


def test_apply_should_create_workspace_file_index(conn):
    _apply_all(conn)

    index_columns = [row[2] for row in conn.execute("PRAGMA index_info(idx_annotations_workspace_file)")]
    assert index_columns == ["workspace_id", "repo", "file_path"]


def test_apply_twice_should_keep_existing_rows(conn):
    _apply_all(conn)
    conn.execute("INSERT INTO workspaces (id) VALUES (1)")
    _insert_annotation(conn)

    _apply_all(conn)

    assert conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 1


def test_insert_should_default_repo_to_empty_string(conn):
    _apply_all(conn)
    conn.execute("INSERT INTO workspaces (id) VALUES (1)")
    _insert_annotation(conn)

    assert conn.execute("SELECT repo, base_commit FROM annotations").fetchone() == ("", None)


def test_delete_workspace_should_cascade_to_annotations(conn):
    _apply_all(conn)
    conn.execute("INSERT INTO workspaces (id) VALUES (1)")
    _insert_annotation(conn)

    conn.execute("DELETE FROM workspaces WHERE id = 1")

    assert conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0


def test_insert_should_fail_when_workspace_missing(conn):
    _apply_all(conn)

    with pytest.raises(sqlite3.IntegrityError):
        _insert_annotation(conn, workspace_id=42)


def test_session_database_should_have_annotations_table(setup_db):
    connection = sqlite3.connect(setup_db)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(annotations)")]
    finally:
        connection.close()

    assert columns == _EXPECTED_COLUMNS
