"""Tests for migration 0045_merge_scope_into_plan.

Verifies the backfill embeds the legacy phase-keyed scope map into each plan
execution item and that the scope_json / scope_status columns are dropped.
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _load_migration_module():
    """Load the 0045 module without invoking yoyo.step side effects."""
    import yoyo as _yoyo

    original_step = _yoyo.step
    _yoyo.step = lambda *args, **kwargs: None
    try:
        module_name = "migration_0045_merge_scope_into_plan"
        if module_name in sys.modules:
            del sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(
            module_name, str(MIGRATIONS_DIR / "0045_merge_scope_into_plan.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    finally:
        _yoyo.step = original_step
    return mod


@pytest.fixture
def legacy_db(tmp_path):
    """A workspaces table that still has the legacy scope columns and one row."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope_json TEXT DEFAULT '{}',
            scope_status TEXT NOT NULL DEFAULT 'pending',
            plan_json TEXT
        )
        """
    )
    return conn


def test_backfill_embeds_scope_into_matching_execution_items(legacy_db):
    scope_json = json.dumps({
        "3.1": {"must": ["src/a/"], "may": ["tests/"]},
        "3.2": {"must": ["src/b/"], "may": []},
    })
    plan_json = json.dumps({
        "description": "",
        "execution": [
            {"id": "3.1", "name": "P1", "tasks": []},
            {"id": "3.2", "name": "P2", "tasks": []},
        ],
    })
    legacy_db.execute(
        "INSERT INTO workspaces (scope_json, scope_status, plan_json) VALUES (?, 'approved', ?)",
        (scope_json, plan_json),
    )
    legacy_db.commit()

    mod = _load_migration_module()
    mod.backfill_scope_into_plan(legacy_db)
    mod.drop_scope_columns(legacy_db)
    legacy_db.commit()

    plan = json.loads(legacy_db.execute("SELECT plan_json FROM workspaces").fetchone()["plan_json"])
    by_id = {item["id"]: item for item in plan["execution"]}
    assert by_id["3.1"]["scope"] == {"must": ["src/a/"], "may": ["tests/"]}
    assert by_id["3.2"]["scope"] == {"must": ["src/b/"], "may": []}

    columns = {row[1] for row in legacy_db.execute("PRAGMA table_info(workspaces)").fetchall()}
    assert "scope_json" not in columns
    assert "scope_status" not in columns


def test_backfill_defaults_empty_scope_when_map_missing_item(legacy_db):
    plan_json = json.dumps({"execution": [{"id": "3.1", "name": "P1", "tasks": []}]})
    legacy_db.execute(
        "INSERT INTO workspaces (scope_json, scope_status, plan_json) VALUES ('{}', 'pending', ?)",
        (plan_json,),
    )
    legacy_db.commit()

    mod = _load_migration_module()
    mod.backfill_scope_into_plan(legacy_db)
    legacy_db.commit()

    plan = json.loads(legacy_db.execute("SELECT plan_json FROM workspaces").fetchone()["plan_json"])
    assert plan["execution"][0]["scope"] == {"must": [], "may": []}


def test_backfill_handles_malformed_and_empty_json(legacy_db):
    legacy_db.execute(
        "INSERT INTO workspaces (scope_json, scope_status, plan_json) VALUES (?, 'pending', ?)",
        ("not json", None),
    )
    legacy_db.commit()

    mod = _load_migration_module()
    mod.backfill_scope_into_plan(legacy_db)
    legacy_db.commit()

    plan = json.loads(legacy_db.execute("SELECT plan_json FROM workspaces").fetchone()["plan_json"])
    assert plan.get("execution", []) == []


def test_drop_columns_is_idempotent(legacy_db):
    plan_json = json.dumps({"execution": []})
    legacy_db.execute(
        "INSERT INTO workspaces (scope_json, scope_status, plan_json) VALUES ('{}', 'pending', ?)",
        (plan_json,),
    )
    legacy_db.commit()

    mod = _load_migration_module()
    mod.drop_scope_columns(legacy_db)
    mod.drop_scope_columns(legacy_db)
    legacy_db.commit()

    columns = {row[1] for row in legacy_db.execute("PRAGMA table_info(workspaces)").fetchall()}
    assert "scope_json" not in columns
    assert "scope_status" not in columns
