"""Tests for review-mode gating in advance/orchestrator.py.

Covers:
- transition_phase's pre-flight file-count check running only when the
  workspace's review mode resolves to a strategy set that includes "files"
  (the 100-file preflight exists solely to bound the per-file fan-out)
- _start_review_pipeline skipping entirely for review modes that resolve to
  no strategies ("manual"), and passing the resolved strategy set through to
  review_pipeline_service.start_in_background otherwise
"""
from unittest.mock import patch

import pytest

import advance.orchestrator as orchestrator
from advance.orchestrator import AdvanceBusinessRuleError, transition_phase
from core.db import get_db
from testing_utils import set_phase


def _get_ws_row(ws_id):
    db = get_db()
    try:
        return db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    finally:
        db.close()


# ── pre-flight file-count gate: gated by the "files" strategy ────────────────────


def test_files_integration_mode_still_enforces_preflight(workspace):
    set_phase(workspace["id"], "3.1.4", review_mode="files_integration")
    ws = _get_ws_row(workspace["id"])
    db = get_db()
    try:
        with patch("services.diff_filter.count_modified", return_value=999999):
            with pytest.raises(AdvanceBusinessRuleError):
                transition_phase(db, ws, "4.0")
    finally:
        db.close()


def test_manual_mode_skips_preflight_file_count(workspace):
    set_phase(workspace["id"], "3.1.4", review_mode="manual")
    ws = _get_ws_row(workspace["id"])
    db = get_db()
    try:
        with patch(
            "services.diff_filter.count_modified",
            side_effect=AssertionError("count_modified must not be called in manual review mode"),
        ):
            result = transition_phase(db, ws, "4.0")
    finally:
        db.close()
    assert result is not None


def test_integration_only_mode_skips_preflight_file_count(workspace):
    set_phase(workspace["id"], "3.1.4", review_mode="integration")
    ws = _get_ws_row(workspace["id"])
    db = get_db()
    try:
        with patch(
            "services.diff_filter.count_modified",
            side_effect=AssertionError("count_modified must not be called without the files strategy"),
        ):
            result = transition_phase(db, ws, "4.0")
    finally:
        db.close()
    assert result is not None


def test_full_mode_still_enforces_preflight(workspace):
    set_phase(workspace["id"], "3.1.4", review_mode="full")
    ws = _get_ws_row(workspace["id"])
    db = get_db()
    try:
        with patch("services.diff_filter.count_modified", return_value=999999):
            with pytest.raises(AdvanceBusinessRuleError):
                transition_phase(db, ws, "4.0")
    finally:
        db.close()


# ── _start_review_pipeline: skipped entirely for manual mode ─────────────────────


def _ws_dict(review_mode, working_dir="/tmp/some-workspace"):
    return {
        "id": 1,
        "working_dir": working_dir,
        "source_branch": "develop",
        "review_mode": review_mode,
    }


def test_start_review_pipeline_skips_entirely_for_manual_mode(monkeypatch):
    monkeypatch.delenv("GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE", raising=False)
    with patch("services.review_pipeline_service.start_in_background") as mock_start:
        orchestrator._start_review_pipeline(_ws_dict("manual"))
    mock_start.assert_not_called()


def test_start_review_pipeline_runs_for_files_integration_mode_with_strategies(monkeypatch):
    monkeypatch.delenv("GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE", raising=False)
    with patch("services.review_pipeline_service.start_in_background") as mock_start:
        orchestrator._start_review_pipeline(_ws_dict("files_integration"))
    mock_start.assert_called_once()
    _, kwargs = mock_start.call_args
    assert kwargs["strategies"] == frozenset({"files", "integration"})


def test_start_review_pipeline_runs_for_full_mode_with_adjudication_strategy(monkeypatch):
    monkeypatch.delenv("GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE", raising=False)
    with patch("services.review_pipeline_service.start_in_background") as mock_start:
        orchestrator._start_review_pipeline(_ws_dict("full"))
    mock_start.assert_called_once()
    _, kwargs = mock_start.call_args
    assert kwargs["strategies"] == frozenset({"files", "integration", "adjudication"})


def test_start_review_pipeline_runs_for_integration_only_mode(monkeypatch):
    monkeypatch.delenv("GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE", raising=False)
    with patch("services.review_pipeline_service.start_in_background") as mock_start:
        orchestrator._start_review_pipeline(_ws_dict("integration"))
    mock_start.assert_called_once()
    _, kwargs = mock_start.call_args
    assert kwargs["strategies"] == frozenset({"integration"})


def test_start_review_pipeline_still_honors_disable_env_var(monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE", "1")
    with patch("services.review_pipeline_service.start_in_background") as mock_start:
        orchestrator._start_review_pipeline(_ws_dict("full"))
    mock_start.assert_not_called()
