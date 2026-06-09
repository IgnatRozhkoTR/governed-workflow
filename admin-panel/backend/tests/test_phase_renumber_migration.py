"""Tests for migration 0038_renumber_done_phase_to_6.

After migration 0039 dropped the ``work_mode_phases`` table, only the
``phase_settings`` renumber leg of 0038 is observable end-to-end.
"""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _load_migration_steps():
    """Return all SQL UPDATE steps captured from 0038."""
    import yoyo as _yoyo

    original_step = _yoyo.step
    captured_sql = []

    def _stub_step(sql, *args, **kwargs):
        if isinstance(sql, str):
            captured_sql.append(sql)

    _yoyo.step = _stub_step
    try:
        module_name = "migration_0038_renumber_done_phase_to_6"
        if module_name in sys.modules:
            del sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(
            module_name,
            str(MIGRATIONS_DIR / "0038_renumber_done_phase_to_6.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step

    return captured_sql


def _apply_steps(conn, steps):
    for sql in steps:
        conn.execute(sql)
    conn.commit()


@pytest.fixture
def pre_migration_db(tmp_path):
    """Minimal DB with a phase_settings row at phase_id='5'."""
    db_path = tmp_path / "pre_migration.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # ``work_mode_phases`` was dropped in 0039 but 0038 still references it,
    # so the synthetic schema must keep it for the test steps to execute.
    conn.executescript("""
        CREATE TABLE work_mode_phases (
            phase_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            position INTEGER NOT NULL,
            PRIMARY KEY (phase_id)
        );
        CREATE TABLE phase_settings (
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT,
            PRIMARY KEY (scope_type, scope_id, phase_id)
        );
    """)

    conn.execute(
        "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled) VALUES ('workspace', 'ws-1', '5', 1)"
    )
    conn.execute(
        "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled) VALUES ('workspace', 'ws-1', '1.0', 1)"
    )

    conn.commit()
    return conn


def test_phase_settings_row_renumbered(pre_migration_db):
    steps = _load_migration_steps()

    _apply_steps(pre_migration_db, steps)

    rows = pre_migration_db.execute(
        "SELECT phase_id FROM phase_settings WHERE scope_id = 'ws-1' ORDER BY phase_id"
    ).fetchall()
    phase_ids = [r["phase_id"] for r in rows]

    assert "5" not in phase_ids
    assert "6" in phase_ids


def test_unrelated_phase_settings_row_unchanged(pre_migration_db):
    steps = _load_migration_steps()

    _apply_steps(pre_migration_db, steps)

    ps = pre_migration_db.execute(
        "SELECT phase_id FROM phase_settings WHERE phase_id = '1.0'"
    ).fetchone()
    assert ps is not None


def test_migration_is_idempotent(pre_migration_db):
    steps = _load_migration_steps()

    _apply_steps(pre_migration_db, steps)
    _apply_steps(pre_migration_db, steps)

    rows = pre_migration_db.execute(
        "SELECT phase_id FROM phase_settings WHERE phase_id IN ('5', '6')"
    ).fetchall()
    phase_ids = [r["phase_id"] for r in rows]

    assert "5" not in phase_ids
    assert phase_ids.count("6") == 1


def test_no_phase_5_rows_in_phase_settings_after_full_migration_suite(setup_db):
    """After the full migration suite runs, phase_settings has no phase_id='5'."""
    from core.db import get_db

    db = get_db()
    try:
        row = db.execute(
            "SELECT COUNT(*) AS cnt FROM phase_settings WHERE phase_id = '5'"
        ).fetchone()
        assert row["cnt"] == 0, f"Found {row['cnt']} phase_settings row(s) with phase_id='5'"
    finally:
        db.close()
