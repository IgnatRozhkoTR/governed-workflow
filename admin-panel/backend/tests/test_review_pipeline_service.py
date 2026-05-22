"""Tests for the headless review pipeline service.

The pipeline shells out to ``claude -p`` per file and per integration agent.
These tests patch the async ``_spawn_claude_agent`` helper to inject canned
envelope JSON, so no real subprocesses are spawned.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import review_pipeline_service
from services.diff_filter import ReviewableFile


def _envelope(payload: dict | str) -> str:
    """Build a ``claude -p --output-format json`` envelope around an agent result."""
    if isinstance(payload, dict):
        result = json.dumps(payload)
    else:
        result = payload
    return json.dumps({"result": result})


def _file_envelope(findings: list[dict]) -> str:
    return _envelope({"findings": findings})


def _wait_for_state(workspace_id: int, terminal_states=("done", "failed"), timeout: float = 5.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = review_pipeline_service.get_status(workspace_id)
        if status and status.state in terminal_states:
            return status
        time.sleep(0.02)
    raise AssertionError(
        f"pipeline did not reach terminal state within {timeout}s; "
        f"last state={status.state if status else 'no-status'}"
    )


def _drop_status(workspace_id: int) -> None:
    review_pipeline_service._STATUS.pop(workspace_id, None)


@pytest.fixture
def repo_with_files(workspace, git_repo):
    """Yield a workspace whose working_dir contains a single source file.

    Submitting review issues writes to the DB via the real
    ``comment_service.submit_review_issue`` and requires the row to point at
    a workspace + file_path that pass downstream readers.
    """
    repo = Path(git_repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "alpha.py").write_text("print('a')\n")
    (repo / "src" / "beta.py").write_text("print('b')\n")
    yield workspace
    _drop_status(workspace["id"])


def _patch_spawn(canned: dict[str, str]):
    """Return a patch that maps (agent, prompt-substring) -> envelope JSON.

    The keys are matched against the agent name. For per-file calls the file
    path is encoded in the prompt; tests provide per-file envelopes keyed by
    the file's basename.
    """

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s):
        # First try exact agent match, then agent+file-path prompt match.
        if agent in canned and isinstance(canned[agent], str):
            return canned[agent]
        for key, value in canned.items():
            if key in agent or key in prompt:
                return value
        return _envelope("")

    return patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=fake_spawn
    )


def test_per_file_findings_are_submitted(repo_with_files):
    ws = repo_with_files
    reviewable = [
        ReviewableFile(path="src/alpha.py", status="M"),
        ReviewableFile(path="src/beta.py", status="M"),
    ]
    canned = {
        "src/alpha.py": _file_envelope([
            {"severity": "major", "type": "logic", "line": 1, "summary": "alpha issue"},
        ]),
        "src/beta.py": _file_envelope([
            {"severity": "critical", "type": "security", "line": 1, "summary": "beta issue"},
        ]),
        "architecture-reviewer": _envelope(""),
        "logic-reviewer": _envelope(""),
        "security-reviewer": _envelope(""),
    }

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=reviewable,
    ), _patch_spawn(canned):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.files["src/alpha.py"].status == "done"
    assert status.files["src/alpha.py"].findings_count == 1
    assert status.files["src/beta.py"].findings_count == 1
    assert status.integration["architecture-reviewer"] == "done"
    assert status.integration["logic-reviewer"] == "done"
    assert status.integration["security-reviewer"] == "done"

    from core.db import get_db
    db = get_db()
    try:
        rows = db.execute(
            "SELECT file_path, text FROM discussions "
            "WHERE workspace_id = ? AND scope = 'review' ORDER BY id",
            (ws["id"],),
        ).fetchall()
    finally:
        db.close()
    paths = [r["file_path"] for r in rows]
    assert "src/alpha.py" in paths
    assert "src/beta.py" in paths


def test_file_reviewer_timeout_is_recorded_as_failure(repo_with_files):
    ws = repo_with_files
    reviewable = [ReviewableFile(path="src/alpha.py", status="M")]

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s):
        if agent == "file-reviewer":
            raise RuntimeError("file-reviewer timeout after 300s")
        return _envelope("")

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=reviewable,
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=fake_spawn
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.files["src/alpha.py"].status == "failed"
    assert "timeout" in (status.files["src/alpha.py"].error or "")

    from core.db import get_db
    db = get_db()
    try:
        rows = db.execute(
            "SELECT text FROM discussions WHERE workspace_id = ? AND scope = 'review'",
            (ws["id"],),
        ).fetchall()
    finally:
        db.close()
    assert any("[review-agent-failure]" in r["text"] for r in rows)


def test_integration_agent_failure_does_not_block_other_agent(repo_with_files):
    ws = repo_with_files

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s):
        if agent == "architecture-reviewer":
            raise RuntimeError("architecture-reviewer exit 1: boom")
        if agent in ("logic-reviewer", "security-reviewer"):
            return _envelope("")
        return _envelope("")

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=[],
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=fake_spawn
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.integration["architecture-reviewer"] == "failed"
    assert status.integration["logic-reviewer"] == "done"
    assert status.integration["security-reviewer"] == "done"


def test_integration_agents_run_concurrently(repo_with_files):
    """All three integration agents must be in-flight at the same instant.

    Each fake spawn registers itself as in-flight, then yields control. If
    the stage ran sequentially the second/third agents would never see the
    first counted as in-flight, so peak concurrency would equal 1. With
    parallel ``asyncio.gather`` peak concurrency equals the agent count.
    """
    ws = repo_with_files
    in_flight = 0
    peak_concurrency = 0

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s):
        nonlocal in_flight, peak_concurrency
        in_flight += 1
        peak_concurrency = max(peak_concurrency, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return _envelope("")

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=[],
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=fake_spawn
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert all(s == "done" for s in status.integration.values())
    assert peak_concurrency == len(review_pipeline_service._INTEGRATION_AGENTS), (
        f"expected all {len(review_pipeline_service._INTEGRATION_AGENTS)} integration "
        f"agents to run concurrently; peak was {peak_concurrency}"
    )


def test_empty_diff_runs_cleanly(repo_with_files):
    ws = repo_with_files

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s):
        return _envelope("")

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=[],
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=fake_spawn
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.files == {}
    assert all(s == "done" for s in status.integration.values())


def test_status_endpoint_returns_snapshot(repo_with_files, client):
    ws = repo_with_files

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s):
        return _envelope("")

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=[],
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=fake_spawn
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        _wait_for_state(ws["id"])

    response = client.get(f"/api/workspaces/{ws['id']}/review-pipeline-status")
    assert response.status_code == 200
    body = response.get_json()
    assert body["workspace_id"] == ws["id"]
    assert body["state"] == "done"


def test_status_endpoint_404_when_no_status(client):
    response = client.get("/api/workspaces/99999/review-pipeline-status")
    assert response.status_code == 404


def test_diff_filter_failure_marks_pipeline_failed(repo_with_files):
    ws = repo_with_files

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        side_effect=RuntimeError("git unavailable"),
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "failed"
    assert "git unavailable" in (status.error or "")


def test_invalid_envelope_recorded_as_file_failure(repo_with_files):
    ws = repo_with_files
    reviewable = [ReviewableFile(path="src/alpha.py", status="M")]

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s):
        if agent == "file-reviewer":
            return "this is not json"
        return _envelope("")

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=reviewable,
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=fake_spawn
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.files["src/alpha.py"].status == "failed"


def test_parse_file_reviewer_findings_filters_non_dict_entries():
    envelope = _file_envelope([
        {"severity": "major", "summary": "ok", "line": 5},
        "not a dict",
        {"severity": "critical", "summary": "also ok", "line": 10},
    ])
    findings = review_pipeline_service._parse_file_reviewer_findings(envelope)
    assert len(findings) == 2
    assert findings[0]["summary"] == "ok"
    assert findings[1]["summary"] == "also ok"


def test_concurrency_env_override(monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_REVIEW_CONCURRENCY", "2")
    assert review_pipeline_service._concurrency() == 2
    monkeypatch.setenv("GOVERNED_WORKFLOW_REVIEW_CONCURRENCY", "garbage")
    assert review_pipeline_service._concurrency() == review_pipeline_service._DEFAULT_CONCURRENCY


def test_timeout_env_override(monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_REVIEW_TIMEOUT_S", "60")
    assert review_pipeline_service._timeout_s() == 60
    monkeypatch.setenv("GOVERNED_WORKFLOW_REVIEW_TIMEOUT_S", "5")
    # minimum floor is 30
    assert review_pipeline_service._timeout_s() == 30
