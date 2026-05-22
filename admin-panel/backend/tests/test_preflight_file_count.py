"""Tests for the pre-flight file-count gate in transition_phase (sub-phase 3.3)."""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from advance.orchestrator import (
    AdvanceBusinessRuleError,
    _check_review_file_count,
    _max_files_for_review,
    transition_phase,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_ws(working_dir):
    return {
        "id": 1,
        "project_id": "proj-preflight",
        "working_dir": working_dir,
        "phase": "3.1.4",
        "last_confirmed_commit": None,
    }


def _make_db(tmp_path):
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
    db.execute("INSERT INTO projects (id, name) VALUES (?, ?)", (ws["project_id"], "Test"))
    db.commit()


def _patch_count(return_value):
    return patch("services.diff_filter.count_modified", return_value=return_value)


# ── _max_files_for_review ─────────────────────────────────────────────────────


def test_max_files_default_is_100():
    assert _max_files_for_review() == 100


def test_max_files_env_var_overrides(monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_MAX_FILES_PER_REVIEW", "50")
    assert _max_files_for_review() == 50


def test_max_files_env_var_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_MAX_FILES_PER_REVIEW", "not-a-number")
    assert _max_files_for_review() == 100


def test_max_files_env_var_zero_clamps_to_one(monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_MAX_FILES_PER_REVIEW", "0")
    assert _max_files_for_review() == 1


# ── _check_review_file_count unit tests ───────────────────────────────────────


def test_check_passes_when_count_under_limit(tmp_path):
    ws = _make_ws(str(tmp_path))
    with _patch_count(99):
        _check_review_file_count(ws)  # must not raise


def test_check_passes_when_count_equals_limit(tmp_path):
    ws = _make_ws(str(tmp_path))
    with _patch_count(100):
        _check_review_file_count(ws)  # exactly at limit — must not raise


def test_check_raises_when_count_over_limit(tmp_path):
    ws = _make_ws(str(tmp_path))
    with _patch_count(101):
        with pytest.raises(AdvanceBusinessRuleError) as exc_info:
            _check_review_file_count(ws)
    msg = str(exc_info.value)
    assert "101" in msg
    assert "100" in msg
    assert "GOVERNED_WORKFLOW_MAX_FILES_PER_REVIEW" in msg
    assert "4.0" in msg


def test_check_message_mentions_split_suggestion(tmp_path):
    ws = _make_ws(str(tmp_path))
    with _patch_count(200):
        with pytest.raises(AdvanceBusinessRuleError) as exc_info:
            _check_review_file_count(ws)
    assert "smaller branches" in str(exc_info.value)


def test_check_env_var_raises_limit_changes_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_MAX_FILES_PER_REVIEW", "10")
    ws = _make_ws(str(tmp_path))
    with _patch_count(11):
        with pytest.raises(AdvanceBusinessRuleError):
            _check_review_file_count(ws)


def test_check_env_var_raises_limit_allows_under(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_MAX_FILES_PER_REVIEW", "10")
    ws = _make_ws(str(tmp_path))
    with _patch_count(10):
        _check_review_file_count(ws)  # exactly at env-var limit — must not raise


def test_check_graceful_when_diff_filter_raises(tmp_path):
    ws = _make_ws(str(tmp_path))
    with patch("services.diff_filter.count_modified", side_effect=RuntimeError("git exploded")):
        _check_review_file_count(ws)  # must not raise; graceful degradation


def test_check_graceful_when_working_dir_missing():
    ws = _make_ws("")
    with patch("services.diff_filter.count_modified", side_effect=AssertionError("must not be called")):
        _check_review_file_count(ws)  # empty working_dir → early return, no call


# ── transition_phase integration ──────────────────────────────────────────────


def test_transition_to_4_0_proceeds_when_under_limit(tmp_path):
    db = _make_db(tmp_path)
    ws = _make_ws(str(tmp_path / "repo"))
    _insert_workspace(db, ws)
    with _patch_count(50):
        result = transition_phase(db, ws, "4.0")
    assert result is not None


def test_transition_to_4_0_proceeds_when_at_limit(tmp_path):
    db = _make_db(tmp_path)
    ws = _make_ws(str(tmp_path / "repo"))
    _insert_workspace(db, ws)
    with _patch_count(100):
        result = transition_phase(db, ws, "4.0")
    assert result is not None


def test_transition_to_4_0_raises_when_over_limit(tmp_path):
    db = _make_db(tmp_path)
    ws = _make_ws(str(tmp_path / "repo"))
    _insert_workspace(db, ws)
    with _patch_count(101):
        with pytest.raises(AdvanceBusinessRuleError):
            transition_phase(db, ws, "4.0")


def test_transition_to_4_0_db_not_updated_on_rejection(tmp_path):
    db = _make_db(tmp_path)
    ws = _make_ws(str(tmp_path / "repo"))
    _insert_workspace(db, ws)
    with _patch_count(200):
        with pytest.raises(AdvanceBusinessRuleError):
            transition_phase(db, ws, "4.0")
    row = db.execute("SELECT phase FROM workspaces WHERE id = ?", (ws["id"],)).fetchone()
    assert row["phase"] == "3.1.4"  # phase must not have been written


def test_non_4_0_transition_never_calls_count_modified(tmp_path):
    db = _make_db(tmp_path)
    ws = _make_ws(str(tmp_path / "repo"))
    _insert_workspace(db, ws)
    with patch(
        "services.diff_filter.count_modified",
        side_effect=AssertionError("count_modified must not be called for non-4.0 transitions"),
    ):
        result = transition_phase(db, ws, "4.1")
    assert result is not None


def test_transition_to_4_0_graceful_when_diff_filter_raises(tmp_path):
    db = _make_db(tmp_path)
    ws = _make_ws(str(tmp_path / "repo"))
    _insert_workspace(db, ws)
    with patch("services.diff_filter.count_modified", side_effect=RuntimeError("git error")):
        result = transition_phase(db, ws, "4.0")
    assert result is not None  # graceful degradation — advance proceeds
