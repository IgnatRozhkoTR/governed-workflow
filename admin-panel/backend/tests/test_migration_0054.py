"""Tests for migration 0054_drop_lsp_and_telegram.

The session database replays every migration, so it shows the fresh-install
result. A hand-built pre-0054 schema covers an existing install and re-running
the step on it.
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "0054_drop_lsp_and_telegram.py"

_PRE_0054_SCHEMA = """
CREATE TABLE verification_profiles (
    id INTEGER PRIMARY KEY, name TEXT, language TEXT, description TEXT, origin TEXT,
    lsp_command TEXT, lsp_args TEXT, lsp_install_check_command TEXT,
    lsp_install_command TEXT, lsp_workspace_config TEXT, lsp_port INTEGER
);
CREATE TABLE project_verification_profiles (
    id INTEGER PRIMARY KEY, profile_id INTEGER, lsp_enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE lsp_instances (id INTEGER PRIMARY KEY, profile_id INTEGER);
CREATE TABLE workspaces (id INTEGER PRIMARY KEY, branch TEXT, channels TEXT DEFAULT '');
CREATE TABLE modules_enabled (id INTEGER PRIMARY KEY, module_id TEXT NOT NULL UNIQUE);
INSERT INTO verification_profiles (name, language, description, origin) VALUES
    ('Java (Gradle)', 'java', 'Java build verification. LSP setup uses jdtls', 'system'),
    ('Kotlin (Gradle)', 'kotlin', 'Kotlin build verification using Gradle. LSP setup uses kotlin-lsp', 'system'),
    ('My Java', 'java', 'custom LSP notes', 'user');
INSERT INTO modules_enabled (module_id) VALUES ('telegram'), ('other');
"""


def _load_apply_step():
    import yoyo

    captured = []
    original_step = yoyo.step
    yoyo.step = lambda apply, rollback=None, **kwargs: captured.append(apply)
    try:
        spec = importlib.util.spec_from_file_location("migration_0054_drop_lsp_and_telegram", MIGRATION_PATH)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    finally:
        yoyo.step = original_step
    return captured[0]


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@pytest.fixture
def pre_0054_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_PRE_0054_SCHEMA)
    yield conn
    conn.close()


def test_fresh_install_has_no_lsp_schema_or_text(setup_db):
    conn = sqlite3.connect(str(setup_db))
    try:
        assert "lsp_instances" not in _tables(conn)
        assert not {c for c in _columns(conn, "verification_profiles") if c.startswith("lsp_")}
        assert "lsp_enabled" not in _columns(conn, "project_verification_profiles")
        assert "channels" not in _columns(conn, "workspaces")
        descriptions = [row[0] for row in conn.execute(
            "SELECT description FROM verification_profiles WHERE origin = 'system'"
        )]
        assert descriptions
        assert not [d for d in descriptions if d and "lsp" in d.lower()]
    finally:
        conn.close()


def test_apply_drops_lsp_schema_and_channels(pre_0054_db):
    _load_apply_step()(pre_0054_db)

    assert "lsp_instances" not in _tables(pre_0054_db)
    assert _columns(pre_0054_db, "verification_profiles") == {"id", "name", "language", "description", "origin"}
    assert _columns(pre_0054_db, "project_verification_profiles") == {"id", "profile_id"}
    assert _columns(pre_0054_db, "workspaces") == {"id", "branch"}


def test_apply_rewrites_only_system_java_and_kotlin_descriptions(pre_0054_db):
    _load_apply_step()(pre_0054_db)

    rows = dict(pre_0054_db.execute("SELECT name, description FROM verification_profiles"))
    assert rows == {
        "Java (Gradle)": "Java build verification.",
        "Kotlin (Gradle)": "Kotlin build verification using Gradle.",
        "My Java": "custom LSP notes",
    }


def test_apply_deletes_only_telegram_module_row(pre_0054_db):
    _load_apply_step()(pre_0054_db)

    assert [row[0] for row in pre_0054_db.execute("SELECT module_id FROM modules_enabled")] == ["other"]


def test_apply_twice_is_a_no_op(pre_0054_db):
    apply_step = _load_apply_step()
    apply_step(pre_0054_db)

    apply_step(pre_0054_db)

    assert "lsp_instances" not in _tables(pre_0054_db)
