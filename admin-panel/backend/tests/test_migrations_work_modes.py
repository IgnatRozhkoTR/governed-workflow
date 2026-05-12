"""Tests for migrations 0029_work_modes and 0030_link_existing_workspaces_to_basic."""
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
def fresh_db(tmp_path):
    """Minimal SQLite DB with projects + workspaces tables for migration testing."""
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
    conn.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES ('p1', 'P', '/p', '2024-01-01')"
    )
    conn.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, created) "
        "VALUES ('p1', 'main', 'main', '/p', '2024-01-01')"
    )
    conn.commit()
    return conn


def _apply_migration_0029(conn: sqlite3.Connection) -> None:
    """Execute the work_modes migration DDL + seed against *conn*."""
    import yoyo as _yoyo

    captured: dict = {"sql_steps": [], "fn_steps": []}
    original_step = _yoyo.step

    def _stub_step(fn_or_sql, *args, **kwargs):
        if callable(fn_or_sql):
            captured["fn_steps"].append(fn_or_sql)
        else:
            captured["sql_steps"].append(fn_or_sql)

    _yoyo.step = _stub_step
    try:
        mod_name = "migration_0029_work_modes_test"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(
            mod_name,
            str(MIGRATIONS_DIR / "0029_work_modes.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step

    for sql in captured["sql_steps"]:
        conn.executescript(sql)
    conn.commit()

    for fn in captured["fn_steps"]:
        fn(conn)
    conn.commit()


def _apply_migration_0030(conn: sqlite3.Connection) -> None:
    """Execute the backfill migration against *conn*."""
    import yoyo as _yoyo

    captured: dict = {"sql_steps": []}
    original_step = _yoyo.step

    def _stub_step(fn_or_sql, *args, **kwargs):
        if not callable(fn_or_sql):
            captured["sql_steps"].append(fn_or_sql)

    _yoyo.step = _stub_step
    try:
        mod_name = "migration_0030_link_workspaces_test"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(
            mod_name,
            str(MIGRATIONS_DIR / "0030_link_existing_workspaces_to_basic.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step

    for sql in captured["sql_steps"]:
        conn.execute(sql)
    conn.commit()


def _apply_migration_0031(conn: sqlite3.Connection) -> None:
    """Execute the extra-modes seed migration against *conn*."""
    import yoyo as _yoyo

    captured: dict = {"fn_steps": []}
    original_step = _yoyo.step

    def _stub_step(fn_or_sql, *args, **kwargs):
        if callable(fn_or_sql):
            captured["fn_steps"].append(fn_or_sql)

    _yoyo.step = _stub_step
    try:
        mod_name = "migration_0031_seed_extra_modes_test"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(
            mod_name,
            str(MIGRATIONS_DIR / "0031_seed_extra_work_modes.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step

    for fn in captured["fn_steps"]:
        fn(conn)
    conn.commit()


class TestWorkModesMigration:
    def test_work_modes_table_seeded_with_basic_origin_system(self, fresh_db):
        _apply_migration_0029(fresh_db)

        row = fresh_db.execute(
            "SELECT name, origin FROM work_modes WHERE name = 'basic'"
        ).fetchone()

        assert row is not None
        assert row["name"] == "basic"
        assert row["origin"] == "system"

    def test_work_mode_phases_populated_with_canonical_ids(self, fresh_db):
        from advance.phases import PHASE_REGISTRY
        from core.phase import is_templated

        _apply_migration_0029(fresh_db)

        basic_id = fresh_db.execute(
            "SELECT id FROM work_modes WHERE name = 'basic'"
        ).fetchone()["id"]
        rows = fresh_db.execute(
            "SELECT phase_id, enabled FROM work_mode_phases WHERE work_mode_id = ?",
            (basic_id,),
        ).fetchall()

        seeded_ids = {row["phase_id"] for row in rows}
        canonical_ids = {pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)}

        assert canonical_ids.issubset(seeded_ids), (
            f"Missing from work_mode_phases: {canonical_ids - seeded_ids}"
        )
        assert all(row["enabled"] == 1 for row in rows), (
            "All seeded phases should have enabled=1"
        )

    def test_existing_workspaces_linked_to_basic_after_0030(self, fresh_db):
        _apply_migration_0029(fresh_db)
        _apply_migration_0030(fresh_db)

        basic_id = fresh_db.execute(
            "SELECT id FROM work_modes WHERE name = 'basic'"
        ).fetchone()["id"]
        workspaces = fresh_db.execute("SELECT id, work_mode_id FROM workspaces").fetchall()

        assert len(workspaces) > 0
        for ws in workspaces:
            assert ws["work_mode_id"] == basic_id, (
                f"Workspace {ws['id']} should point at basic ({basic_id}), "
                f"got {ws['work_mode_id']}"
            )


class TestExtraModesMigration:
    """Regression tests for migration 0031 (lite + solo seeded presets)."""

    def test_lite_mode_disables_blind_review_phases(self, fresh_db):
        _apply_migration_0029(fresh_db)
        _apply_migration_0031(fresh_db)

        lite_id = fresh_db.execute(
            "SELECT id FROM work_modes WHERE name = 'lite'"
        ).fetchone()["id"]
        rows = fresh_db.execute(
            "SELECT phase_id, enabled FROM work_mode_phases WHERE work_mode_id = ?",
            (lite_id,),
        ).fetchall()

        disabled = {r["phase_id"] for r in rows if r["enabled"] == 0}
        assert disabled == {"4.0", "4.1", "4.2"}

    def test_solo_mode_disables_user_gate_phases_only(self, fresh_db):
        """``solo`` disables exactly the user-gate phases registered in the
        canonical sequence: ``1.4`` (preparation review), ``4.2`` (final
        approval), and the templated ``3.x.3`` (per-item commit approval)."""
        _apply_migration_0029(fresh_db)
        _apply_migration_0031(fresh_db)

        solo_id = fresh_db.execute(
            "SELECT id FROM work_modes WHERE name = 'solo'"
        ).fetchone()["id"]
        rows = fresh_db.execute(
            "SELECT phase_id, enabled FROM work_mode_phases WHERE work_mode_id = ?",
            (solo_id,),
        ).fetchall()

        disabled = {r["phase_id"] for r in rows if r["enabled"] == 0}
        assert disabled, "solo must disable a non-empty set of phase ids"
        assert disabled == {"1.4", "4.2", "3.x.3"}

    def test_solo_mode_phase_ids_are_all_registered(self, fresh_db):
        """No row in the solo seed references an unregistered phase id."""
        from advance.phases import PHASE_REGISTRY

        _apply_migration_0029(fresh_db)
        _apply_migration_0031(fresh_db)

        solo_id = fresh_db.execute(
            "SELECT id FROM work_modes WHERE name = 'solo'"
        ).fetchone()["id"]
        rows = fresh_db.execute(
            "SELECT phase_id FROM work_mode_phases WHERE work_mode_id = ?",
            (solo_id,),
        ).fetchall()

        unknown = [r["phase_id"] for r in rows if r["phase_id"] not in PHASE_REGISTRY]
        assert unknown == [], f"solo references unregistered phase ids: {unknown}"

    def test_solo_mode_origin_is_system(self, fresh_db):
        _apply_migration_0029(fresh_db)
        _apply_migration_0031(fresh_db)

        row = fresh_db.execute(
            "SELECT origin FROM work_modes WHERE name = 'solo'"
        ).fetchone()
        assert row["origin"] == "system"

    def test_extra_modes_migration_is_idempotent(self, fresh_db):
        """Re-running 0031 against a DB that already has the modes is a no-op."""
        _apply_migration_0029(fresh_db)
        _apply_migration_0031(fresh_db)
        _apply_migration_0031(fresh_db)

        names = [
            row["name"] for row in fresh_db.execute(
                "SELECT name FROM work_modes WHERE name IN ('lite', 'solo') ORDER BY name"
            ).fetchall()
        ]
        assert names == ["lite", "solo"]
