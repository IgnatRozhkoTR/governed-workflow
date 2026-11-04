"""Tests for migration 0052_kotlin_lsp_launcher.

Verifies the Kotlin (Gradle) profile's lsp_command is rewritten to route
through the direct-JVM launcher script, and that neither direction ever
clobbers a user-customized lsp_command value.
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

_OLD_COMMAND = "kotlin-lsp"
_NEW_COMMAND = "{tools_dir}/kotlin-lsp-launcher.py"
_CUSTOM_COMMAND = "/usr/local/bin/my-kotlin-lsp"


def _load_migration_module():
    """Load the 0052 module without invoking yoyo.step side effects."""
    import yoyo as _yoyo

    original_step = _yoyo.step
    _yoyo.step = lambda *args, **kwargs: None
    try:
        module_name = "migration_0052_kotlin_lsp_launcher"
        if module_name in sys.modules:
            del sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(
            module_name, str(MIGRATIONS_DIR / "0052_kotlin_lsp_launcher.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step
    return mod


@pytest.fixture
def kotlin_profile_db(tmp_path, request):
    """SQLite DB with a single Kotlin (Gradle) system profile seeded with *lsp_command*."""
    lsp_command = getattr(request, "param", _OLD_COMMAND)
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE verification_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'system',
            lsp_command TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO verification_profiles (name, origin, lsp_command) VALUES (?, ?, ?)",
        ("Kotlin (Gradle)", "system", lsp_command),
    )
    conn.commit()
    yield conn
    conn.close()


def _read_command(conn):
    row = conn.execute(
        "SELECT lsp_command FROM verification_profiles WHERE name = 'Kotlin (Gradle)'"
    ).fetchone()
    return row[0]


def test_apply_rewrites_default_command_to_launcher(kotlin_profile_db):
    mod = _load_migration_module()

    mod.apply_step(kotlin_profile_db)

    assert _read_command(kotlin_profile_db) == _NEW_COMMAND


@pytest.mark.parametrize("kotlin_profile_db", [_CUSTOM_COMMAND], indirect=True)
def test_apply_never_clobbers_user_customized_command(kotlin_profile_db):
    mod = _load_migration_module()

    mod.apply_step(kotlin_profile_db)

    assert _read_command(kotlin_profile_db) == _CUSTOM_COMMAND


@pytest.mark.parametrize("kotlin_profile_db", [_NEW_COMMAND], indirect=True)
def test_rollback_restores_default_command(kotlin_profile_db):
    mod = _load_migration_module()

    mod.rollback_step(kotlin_profile_db)

    assert _read_command(kotlin_profile_db) == _OLD_COMMAND


@pytest.mark.parametrize("kotlin_profile_db", [_CUSTOM_COMMAND], indirect=True)
def test_rollback_never_clobbers_user_customized_command(kotlin_profile_db):
    mod = _load_migration_module()

    mod.rollback_step(kotlin_profile_db)

    assert _read_command(kotlin_profile_db) == _CUSTOM_COMMAND


def test_apply_is_idempotent(kotlin_profile_db):
    mod = _load_migration_module()

    mod.apply_step(kotlin_profile_db)
    mod.apply_step(kotlin_profile_db)

    assert _read_command(kotlin_profile_db) == _NEW_COMMAND
