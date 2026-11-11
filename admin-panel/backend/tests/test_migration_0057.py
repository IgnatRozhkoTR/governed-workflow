"""Tests for migration 0057_resolved_review_threads_clear_open_resolution."""
import importlib.util
import sqlite3
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "migrations" / "0057_resolved_review_threads_clear_open_resolution.py"
)

_SCHEMA = """
CREATE TABLE discussions (
    id INTEGER PRIMARY KEY, parent_id INTEGER, scope TEXT, status TEXT, resolution TEXT
);
INSERT INTO discussions (id, parent_id, scope, status, resolution) VALUES
    (1, NULL, 'review', 'resolved', 'open'),
    (2, NULL, 'review', 'open', 'open'),
    (3, NULL, 'review', 'resolved', 'fixed'),
    (4, NULL, 'plan', 'resolved', NULL),
    (5, 1, 'review', 'resolved', 'open');
"""


def _load_apply_step():
    import yoyo

    captured = []
    original_step = yoyo.step
    yoyo.step = lambda apply, rollback=None, **kwargs: captured.append(apply)
    try:
        spec = importlib.util.spec_from_file_location("migration_0057", MIGRATION_PATH)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    finally:
        yoyo.step = original_step
    return captured[0]


def _resolutions(conn):
    return dict(conn.execute("SELECT id, resolution FROM discussions").fetchall())


def test_apply_resolves_only_resolved_open_review_roots():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)

    _load_apply_step()(conn)

    assert _resolutions(conn) == {1: "out_of_scope", 2: "open", 3: "fixed", 4: None, 5: "open"}


def test_apply_twice_is_a_no_op():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    apply_step = _load_apply_step()
    apply_step(conn)

    apply_step(conn)

    assert _resolutions(conn)[1] == "out_of_scope"


def test_apply_without_discussions_table_does_nothing():
    conn = sqlite3.connect(":memory:")

    _load_apply_step()(conn)
