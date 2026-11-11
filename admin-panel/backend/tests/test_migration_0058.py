"""Tests for migration 0058_plan_comment_stable_targets."""
import importlib.util
import sqlite3
from pathlib import Path

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "0058_plan_comment_stable_targets.py"

_ROWS = [
    (1, "plan", "Entire plan"),
    (2, "plan", "Весь план"),
    (3, "plan", "Sub-phase: 1.1 Backend work"),
    (4, "plan", "Под-фаза: 2.3 Фронтенд"),
    (5, "plan", "Sub-phase: 3.1 "),
    (6, "plan", "Task: Add endpoint: v2"),
    (7, "plan", "plan"),
    (8, "plan", "subphase:1.1"),
    (9, "plan", "task:Add endpoint"),
    (10, "plan", "Some custom target"),
    (11, "plan", None),
    (12, "review", "Task: not a plan comment"),
]


def _load_apply_step():
    import yoyo

    captured = []
    original_step = yoyo.step
    yoyo.step = lambda apply, rollback=None, **kwargs: captured.append(apply)
    try:
        spec = importlib.util.spec_from_file_location("migration_0058", MIGRATION_PATH)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    finally:
        yoyo.step = original_step
    return captured[0]


def _seeded_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE discussions (id INTEGER PRIMARY KEY, scope TEXT, target TEXT)")
    conn.executemany("INSERT INTO discussions (id, scope, target) VALUES (?, ?, ?)", _ROWS)
    return conn


def _targets(conn):
    return dict(conn.execute("SELECT id, target FROM discussions").fetchall())


def test_apply_rewrites_english_labels():
    conn = _seeded_conn()

    _load_apply_step()(conn)

    targets = _targets(conn)
    assert targets[1] == "plan"
    assert targets[3] == "subphase:1.1"
    assert targets[5] == "subphase:3.1"
    assert targets[6] == "task:Add endpoint: v2"


def test_apply_rewrites_russian_labels():
    conn = _seeded_conn()

    _load_apply_step()(conn)

    targets = _targets(conn)
    assert targets[2] == "plan"
    assert targets[4] == "subphase:2.3"


def test_apply_keeps_migrated_unknown_null_and_non_plan_targets():
    conn = _seeded_conn()

    _load_apply_step()(conn)

    targets = _targets(conn)
    assert targets[7] == "plan"
    assert targets[8] == "subphase:1.1"
    assert targets[9] == "task:Add endpoint"
    assert targets[10] == "Some custom target"
    assert targets[11] is None
    assert targets[12] == "Task: not a plan comment"


def test_apply_twice_is_a_no_op():
    conn = _seeded_conn()
    apply_step = _load_apply_step()
    apply_step(conn)
    after_first = _targets(conn)

    apply_step(conn)

    assert _targets(conn) == after_first


def test_apply_without_discussions_table_does_nothing():
    conn = sqlite3.connect(":memory:")

    _load_apply_step()(conn)
