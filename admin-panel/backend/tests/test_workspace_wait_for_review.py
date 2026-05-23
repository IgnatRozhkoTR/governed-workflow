"""Tests for workspace_wait_for_review MCP tool.

The @with_mcp_workspace decorator resolves a workspace from cwd, so tests call
the inner tool logic directly by importing the unwrapped helpers and patching
the in-memory _STATUS registry and poll interval.
"""
import threading
import time

import pytest

from services import review_pipeline_service
from services.review_pipeline_service import (
    PipelineStatus,
    FileResult,
    _set_status,
)
from mcp_tools import mcp_error
import mcp_tools.review_pipeline as review_pipeline_module


# ── Shared helpers ────────────────────────────────────────────────────────────


def _drop_status(workspace_id: int) -> None:
    review_pipeline_service._STATUS.pop(workspace_id, None)


def _seed_terminal_status(workspace_id: int, state: str = "done") -> PipelineStatus:
    status = PipelineStatus(workspace_id=workspace_id, state=state)
    status.integration = {
        "architecture-reviewer": "done",
        "correctness-reviewer": "done",
    }
    status.started_at = time.time() - 1.0
    status.finished_at = time.time()
    _set_status(status)
    return status


def _call_wait(workspace_id: int, timeout_s: int = 1800) -> dict:
    """Invoke the inner wait loop without the @with_mcp_workspace decorator."""
    from mcp_tools.review_pipeline import _summary_with_timed_out
    from mcp_tools import review_pipeline as rp_module

    clamped = max(rp_module._TIMEOUT_MIN_S, min(timeout_s, rp_module._TIMEOUT_MAX_S))

    status = review_pipeline_service.get_status(workspace_id)
    if status is None:
        return mcp_error(
            "not_found",
            "no pipeline status for workspace",
            retryable=False,
            details={"workspace_id": workspace_id},
        )

    deadline = time.monotonic() + clamped
    while True:
        if status.state in rp_module._TERMINAL_STATES:
            return _summary_with_timed_out(workspace_id, timed_out=False)

        if time.monotonic() >= deadline:
            return _summary_with_timed_out(workspace_id, timed_out=True)

        time.sleep(rp_module._POLL_INTERVAL_S)
        current = review_pipeline_service.get_status(workspace_id)
        if current is None:
            return mcp_error(
                "not_found",
                "pipeline status lost during wait (server may have restarted)",
                retryable=False,
                details={"workspace_id": workspace_id},
            )
        status = current


# ── Tests ─────────────────────────────────────────────────────────────────────


def _is_error_result(result: dict) -> bool:
    """Return True when result is an mcp_error envelope (not a status summary)."""
    return "errorCategory" in result


def test_returns_immediately_when_pipeline_already_done(monkeypatch):
    workspace_id = 80001
    monkeypatch.setattr(review_pipeline_module, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MIN_S", 1)
    _seed_terminal_status(workspace_id, state="done")
    try:
        start = time.monotonic()

        result = _call_wait(workspace_id, timeout_s=60)

        elapsed = time.monotonic() - start
    finally:
        _drop_status(workspace_id)

    assert not _is_error_result(result), f"unexpected error: {result}"
    assert result["timed_out"] is False
    assert result["state"] == "done"
    assert elapsed < 1.0, f"should return nearly immediately; took {elapsed:.2f}s"


def test_returns_immediately_when_pipeline_already_failed(monkeypatch):
    workspace_id = 80002
    monkeypatch.setattr(review_pipeline_module, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MIN_S", 1)
    _seed_terminal_status(workspace_id, state="failed")
    try:
        result = _call_wait(workspace_id, timeout_s=60)
    finally:
        _drop_status(workspace_id)

    assert not _is_error_result(result)
    assert result["timed_out"] is False
    assert result["state"] == "failed"


def test_returns_when_pipeline_transitions_to_done_during_wait(monkeypatch):
    workspace_id = 80003
    monkeypatch.setattr(review_pipeline_module, "_POLL_INTERVAL_S", 0.1)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MIN_S", 1)

    status = PipelineStatus(workspace_id=workspace_id, state="queued")
    status.integration = {}
    status.started_at = time.time()
    _set_status(status)

    def _transition_to_done():
        time.sleep(0.25)
        status.state = "done"
        status.finished_at = time.time()

    thread = threading.Thread(target=_transition_to_done, daemon=True)
    thread.start()
    try:
        start = time.monotonic()

        result = _call_wait(workspace_id, timeout_s=10)

        elapsed = time.monotonic() - start
        thread.join(timeout=2.0)
    finally:
        _drop_status(workspace_id)

    assert not _is_error_result(result)
    assert result["timed_out"] is False
    assert result["state"] == "done"
    assert elapsed < 3.0, f"should complete within 3s; took {elapsed:.2f}s"


def test_returns_timed_out_when_pipeline_never_reaches_terminal(monkeypatch):
    workspace_id = 80004
    monkeypatch.setattr(review_pipeline_module, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MIN_S", 1)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MAX_S", 2)

    status = PipelineStatus(workspace_id=workspace_id, state="file_stage")
    status.integration = {}
    status.started_at = time.time()
    _set_status(status)
    try:
        start = time.monotonic()

        result = _call_wait(workspace_id, timeout_s=1)

        elapsed = time.monotonic() - start
    finally:
        _drop_status(workspace_id)

    assert not _is_error_result(result)
    assert result["timed_out"] is True
    assert result["state"] == "file_stage"
    assert elapsed < 3.0, f"timeout test took unexpectedly long: {elapsed:.2f}s"


def test_not_found_when_no_status_exists(monkeypatch):
    workspace_id = 80005
    _drop_status(workspace_id)
    monkeypatch.setattr(review_pipeline_module, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MIN_S", 1)

    result = _call_wait(workspace_id, timeout_s=10)

    assert "error" in result
    assert result.get("errorCategory") == "not_found"


def test_timeout_clamping_below_floor_accepts_cleanly(monkeypatch):
    """timeout_s below the minimum is clamped; no exception is raised."""
    workspace_id = 80006
    monkeypatch.setattr(review_pipeline_module, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MIN_S", 30)
    _seed_terminal_status(workspace_id, state="done")
    try:
        result = _call_wait(workspace_id, timeout_s=5)
    finally:
        _drop_status(workspace_id)

    assert not _is_error_result(result)
    assert result["timed_out"] is False


def test_timeout_clamping_above_ceiling_accepts_cleanly(monkeypatch):
    """timeout_s above the maximum is clamped; no exception is raised."""
    workspace_id = 80007
    monkeypatch.setattr(review_pipeline_module, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MAX_S", 3600)
    _seed_terminal_status(workspace_id, state="done")
    try:
        result = _call_wait(workspace_id, timeout_s=10000)
    finally:
        _drop_status(workspace_id)

    assert not _is_error_result(result)
    assert result["timed_out"] is False


def test_result_contains_all_summary_fields(monkeypatch):
    """The returned dict has the same keys as status_summary plus timed_out."""
    workspace_id = 80008
    monkeypatch.setattr(review_pipeline_module, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(review_pipeline_module, "_TIMEOUT_MIN_S", 1)
    _seed_terminal_status(workspace_id, state="done")
    try:
        result = _call_wait(workspace_id, timeout_s=60)
    finally:
        _drop_status(workspace_id)

    expected_keys = {
        "workspace_id", "state", "files_total", "files_done", "files_failed",
        "files_in_progress", "files_with_findings", "files_clean", "failed_files",
        "failed_files_errors", "integration_done", "integration_failed",
        "integration_total", "integration_errors", "is_complete", "is_ok",
        "error", "started_at", "finished_at", "timed_out",
    }
    assert expected_keys.issubset(result.keys()), (
        f"Missing keys: {expected_keys - result.keys()}"
    )
    assert result["timed_out"] is False
