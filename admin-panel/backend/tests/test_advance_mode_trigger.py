"""Tests for major-phase-boundary advance-action file writing in transition_phase."""
import os
import sqlite3

import pytest

from advance.orchestrator import transition_phase, _is_major_transition
from services.advance_mode_service import set_modes


# ── Unit: boundary detection ──────────────────────────────────────────────────


def test_is_major_transition_detects_crossing():
    assert _is_major_transition("1.4", "2.0") is True


def test_is_major_transition_sub_phase_only():
    assert _is_major_transition("3.1.0", "3.1.1") is False


def test_is_major_transition_same_major():
    assert _is_major_transition("2.0", "2.1") is False


def test_is_major_transition_bad_input_is_safe():
    assert _is_major_transition("", "2.0") is False
    assert _is_major_transition("1.4", "") is False


# ── Integration: file-write behaviour ─────────────────────────────────────────


def _make_ws(ws_id, project_id, working_dir, phase):
    return {
        "id": ws_id,
        "project_id": project_id,
        "working_dir": working_dir,
        "phase": phase,
        "last_confirmed_commit": None,
    }


def _make_db(tmp_path):
    """Minimal in-memory-style SQLite DB with the tables transition_phase touches."""
    db = sqlite3.connect(str(tmp_path / "test.db"))
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT
        )
    """)
    db.execute("""
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            project_id TEXT,
            phase TEXT,
            last_confirmed_commit TEXT
        )
    """)
    db.execute("""
        CREATE TABLE phase_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            from_phase TEXT,
            to_phase TEXT,
            time TEXT,
            commit_hash TEXT
        )
    """)
    db.execute("""
        CREATE TABLE project_advance_modes (
            project_id TEXT NOT NULL,
            major_phase INTEGER NOT NULL,
            mode TEXT NOT NULL DEFAULT 'none',
            PRIMARY KEY (project_id, major_phase)
        )
    """)
    db.commit()
    return db


def _insert_workspace(db, ws):
    db.execute(
        "INSERT INTO workspaces (id, project_id, phase, last_confirmed_commit) VALUES (?, ?, ?, ?)",
        (ws["id"], ws["project_id"], ws["phase"], ws["last_confirmed_commit"]),
    )
    db.execute(
        "INSERT INTO projects (id, name) VALUES (?, ?)",
        (ws["project_id"], "Test Project"),
    )
    db.commit()


def _action_file(working_dir):
    return os.path.join(working_dir, ".claude", "state", "pending-advance-action")


def test_major_transition_compact_mode_writes_file(tmp_path):
    db = _make_db(tmp_path)
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-1"

    ws = _make_ws(1, project_id, working_dir, "1.4")
    _insert_workspace(db, ws)
    set_modes(db, project_id, {2: "compact"})

    result = transition_phase(db, ws, "2.0")

    assert result is True
    action_file = _action_file(working_dir)
    assert os.path.isfile(action_file), "pending-advance-action file must be written"
    assert open(action_file).read() == "compact"


def test_major_transition_clear_mode_writes_file(tmp_path):
    db = _make_db(tmp_path)
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-2"

    ws = _make_ws(2, project_id, working_dir, "2.1")
    _insert_workspace(db, ws)
    set_modes(db, project_id, {3: "clear"})

    result = transition_phase(db, ws, "3.1.0")

    assert result is True
    action_file = _action_file(working_dir)
    assert os.path.isfile(action_file)
    assert open(action_file).read() == "clear"


def test_sub_phase_transition_writes_no_file(tmp_path):
    db = _make_db(tmp_path)
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-3"

    ws = _make_ws(3, project_id, working_dir, "3.1.0")
    _insert_workspace(db, ws)
    set_modes(db, project_id, {3: "compact"})

    result = transition_phase(db, ws, "3.1.1")

    assert result is True
    assert not os.path.isfile(_action_file(working_dir))


def test_major_transition_none_mode_writes_no_file(tmp_path):
    db = _make_db(tmp_path)
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-4"

    ws = _make_ws(4, project_id, working_dir, "1.4")
    _insert_workspace(db, ws)
    # mode defaults to 'none'; no explicit set_modes call needed

    result = transition_phase(db, ws, "2.0")

    assert result is True
    assert not os.path.isfile(_action_file(working_dir))


def test_missing_working_dir_is_graceful(tmp_path):
    db = _make_db(tmp_path)
    project_id = "proj-5"
    non_existent_dir = str(tmp_path / "does_not_exist")

    ws = _make_ws(5, project_id, non_existent_dir, "1.4")
    _insert_workspace(db, ws)
    set_modes(db, project_id, {2: "compact"})

    # Must not raise; transition still succeeds
    result = transition_phase(db, ws, "2.0")

    assert result is True
    assert not os.path.isfile(_action_file(non_existent_dir))
