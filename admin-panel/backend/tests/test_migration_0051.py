"""Tests for migration 0051_lsp_cache_dir_kotlin.

Verifies the Kotlin (Gradle) profile's lsp_args are rewritten to route
kotlin-lsp's config/system dirs through the {lsp_cache_dir} placeholder, and
that neither direction ever clobbers a user-customized lsp_args value.
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

_OLD_ARGS = '["--stdio"]'
_NEW_ARGS = (
    '["-Didea.config.path={lsp_cache_dir}/config", '
    '"-Didea.system.path={lsp_cache_dir}/system", "--stdio"]'
)
_CUSTOM_ARGS = '["--stdio", "--custom-flag"]'


def _load_migration_module():
    """Load the 0051 module without invoking yoyo.step side effects."""
    import yoyo as _yoyo

    original_step = _yoyo.step
    _yoyo.step = lambda *args, **kwargs: None
    try:
        module_name = "migration_0051_lsp_cache_dir_kotlin"
        if module_name in sys.modules:
            del sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(
            module_name, str(MIGRATIONS_DIR / "0051_lsp_cache_dir_kotlin.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step
    return mod


@pytest.fixture
def kotlin_profile_db(tmp_path, request):
    """SQLite DB with a single Kotlin (Gradle) system profile seeded with *lsp_args*."""
    lsp_args = getattr(request, "param", _OLD_ARGS)
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE verification_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'system',
            lsp_args TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO verification_profiles (name, origin, lsp_args) VALUES (?, ?, ?)",
        ("Kotlin (Gradle)", "system", lsp_args),
    )
    conn.commit()
    yield conn
    conn.close()


def _read_args(conn):
    row = conn.execute(
        "SELECT lsp_args FROM verification_profiles WHERE name = 'Kotlin (Gradle)'"
    ).fetchone()
    return row[0]


def test_apply_rewrites_default_args_to_cache_dir_placeholders(kotlin_profile_db):
    mod = _load_migration_module()

    mod.apply_step(kotlin_profile_db)

    assert _read_args(kotlin_profile_db) == _NEW_ARGS


@pytest.mark.parametrize("kotlin_profile_db", [_CUSTOM_ARGS], indirect=True)
def test_apply_never_clobbers_user_customized_args(kotlin_profile_db):
    mod = _load_migration_module()

    mod.apply_step(kotlin_profile_db)

    assert _read_args(kotlin_profile_db) == _CUSTOM_ARGS


@pytest.mark.parametrize("kotlin_profile_db", [_NEW_ARGS], indirect=True)
def test_rollback_restores_default_args(kotlin_profile_db):
    mod = _load_migration_module()

    mod.rollback_step(kotlin_profile_db)

    assert _read_args(kotlin_profile_db) == _OLD_ARGS


@pytest.mark.parametrize("kotlin_profile_db", [_CUSTOM_ARGS], indirect=True)
def test_rollback_never_clobbers_user_customized_args(kotlin_profile_db):
    mod = _load_migration_module()

    mod.rollback_step(kotlin_profile_db)

    assert _read_args(kotlin_profile_db) == _CUSTOM_ARGS


def test_apply_is_idempotent(kotlin_profile_db):
    mod = _load_migration_module()

    mod.apply_step(kotlin_profile_db)
    mod.apply_step(kotlin_profile_db)

    assert _read_args(kotlin_profile_db) == _NEW_ARGS
