"""Tests for review-mode strategy gating in the headless review pipeline.

Extends the patterns in ``test_review_pipeline_service.py`` (patch the async
``_spawn_claude_agent`` helper) to cover which stages run for each
``strategies`` set passed to ``start_in_background`` — the mechanism
``advance.orchestrator`` uses to translate a workspace's review mode into
pipeline behavior.
"""
from __future__ import annotations

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
    if isinstance(payload, dict):
        result = json.dumps(payload)
    else:
        result = payload
    return json.dumps({"result": result})


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
    repo = Path(git_repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "alpha.py").write_text("print('a')\n")
    yield workspace
    _drop_status(workspace["id"])


def _always_empty_spawn():
    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s, suppress_mcp=False):
        return _envelope("")
    return fake_spawn


# ── manual mode: no strategies ────────────────────────────────────────────────────


def test_manual_strategies_run_no_stages(repo_with_files):
    ws = repo_with_files
    reviewable = [ReviewableFile(path="src/alpha.py", status="M")]

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        side_effect=AssertionError("files strategy disabled — must not list reviewable files"),
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=_always_empty_spawn()
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
            strategies=frozenset(),
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.files == {}
    assert status.integration == {}
    assert status.adjudication == "skipped"

    summary = review_pipeline_service.status_summary(ws["id"])
    assert summary["stages"] == []
    assert summary["files_total"] == 0
    assert summary["integration_total"] == 0
    assert summary["is_complete"] is True
    assert summary["is_ok"] is True


# ── integration-only mode: skips the file fan-out ─────────────────────────────────


def test_integration_only_strategies_skip_file_stage(repo_with_files):
    ws = repo_with_files

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        side_effect=AssertionError("files strategy disabled — must not list reviewable files"),
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=_always_empty_spawn()
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
            strategies=frozenset({"integration"}),
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.files == {}
    assert status.integration == {"architecture-reviewer": "done", "correctness-reviewer": "done"}
    assert status.adjudication == "skipped"

    summary = review_pipeline_service.status_summary(ws["id"])
    assert summary["stages"] == ["integration"]
    assert summary["files_total"] == 0
    assert summary["integration_total"] == 2
    assert summary["integration_done"] == 2
    assert summary["is_ok"] is True


# ── files-only mode: skips the integration pair ───────────────────────────────────


def test_files_only_strategies_skip_integration_stage(repo_with_files):
    ws = repo_with_files
    reviewable = [ReviewableFile(path="src/alpha.py", status="M")]

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=reviewable,
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=_always_empty_spawn()
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
            strategies=frozenset({"files"}),
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.files["src/alpha.py"].status == "done"
    assert status.integration == {}
    assert status.adjudication == "skipped"

    summary = review_pipeline_service.status_summary(ws["id"])
    assert summary["stages"] == ["files"]
    assert summary["files_total"] == 1
    assert summary["integration_total"] == 0
    assert summary["is_ok"] is True


# ── full mode: adjudication stage runs after integration ──────────────────────────


def test_full_strategies_run_adjudication_stage(repo_with_files):
    ws = repo_with_files
    reviewable = [ReviewableFile(path="src/alpha.py", status="M")]

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=reviewable,
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=_always_empty_spawn()
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
            strategies=frozenset({"files", "integration", "adjudication"}),
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.adjudication == "done"

    summary = review_pipeline_service.status_summary(ws["id"])
    assert summary["stages"] == ["adjudication", "files", "integration"]
    assert summary["adjudication"] == "done"
    assert summary["adjudication_error"] is None
    assert summary["is_complete"] is True
    assert summary["is_ok"] is True


def test_adjudication_agent_failure_does_not_fail_the_run(repo_with_files):
    """Matches integration-stage error semantics: a failed self-submitting
    agent is captured on the status, not raised, and the pipeline still
    reaches 'done' — but is_ok flips to False."""
    ws = repo_with_files

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s, suppress_mcp=False):
        if agent == "resolution-reviewer":
            raise RuntimeError("resolution-reviewer exit 1: boom")
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
            strategies=frozenset({"integration", "adjudication"}),
        )
        status = _wait_for_state(ws["id"])

    assert status.state == "done"
    assert status.adjudication == "failed"
    assert "boom" in status.adjudication_error

    summary = review_pipeline_service.status_summary(ws["id"])
    assert summary["is_complete"] is True
    assert summary["is_ok"] is False
    assert "boom" in summary["adjudication_error"]


def test_adjudication_agent_is_error_envelope_counts_as_failure(repo_with_files):
    ws = repo_with_files
    is_error_envelope = json.dumps({"is_error": True, "error": "agent crashed"})

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s, suppress_mcp=False):
        if agent == "resolution-reviewer":
            return is_error_envelope
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
            strategies=frozenset({"integration", "adjudication"}),
        )
        status = _wait_for_state(ws["id"])

    summary = review_pipeline_service.status_summary(ws["id"])
    assert summary["adjudication"] == "failed"
    assert summary["is_ok"] is False
    assert "is_error=True" in status.adjudication_error


# ── default strategies: backward compatibility ─────────────────────────────────────


def test_start_in_background_default_strategies_are_files_and_integration(repo_with_files):
    ws = repo_with_files

    with patch.object(
        review_pipeline_service.diff_filter, "list_reviewable_files",
        return_value=[],
    ), patch.object(
        review_pipeline_service, "_spawn_claude_agent", side_effect=_always_empty_spawn()
    ):
        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(ws["working_dir"]),
            base_branch="develop",
        )
        status = _wait_for_state(ws["id"])

    assert status.stages == ["files", "integration"]
    assert status.adjudication == "skipped"


# ── _run_adjudication_agent prompt construction ─────────────────────────────────────


def test_run_adjudication_agent_embeds_diff_and_base_ref(tmp_path):
    import asyncio
    from services.review_pipeline_service import _run_adjudication_agent

    captured_prompt: list[str] = []

    async def fake_spawn(agent, prompt, project_path, max_turns, timeout_s, suppress_mcp=False):
        captured_prompt.append(prompt)
        return "{}"

    with patch("services.review_pipeline_service._get_branch_diff", return_value="SENTINEL_DIFF"), \
         patch("services.review_pipeline_service._spawn_claude_agent", side_effect=fake_spawn):
        asyncio.run(_run_adjudication_agent(1, tmp_path, "origin/develop"))

    assert len(captured_prompt) == 1
    assert "SENTINEL_DIFF" in captured_prompt[0]
    assert "origin/develop" in captured_prompt[0]


def test_run_adjudication_agent_passes_no_max_turns(tmp_path):
    import asyncio
    from services.review_pipeline_service import _run_adjudication_agent

    recorded_kwargs: list[dict] = []

    async def fake_spawn(**kwargs):
        recorded_kwargs.append(kwargs)
        return "{}"

    with patch("services.review_pipeline_service._get_branch_diff", return_value=""), \
         patch("services.review_pipeline_service._spawn_claude_agent", side_effect=fake_spawn):
        asyncio.run(_run_adjudication_agent(1, tmp_path, "origin/main"))

    assert len(recorded_kwargs) == 1
    assert recorded_kwargs[0]["max_turns"] is None
    assert recorded_kwargs[0]["agent"] == "resolution-reviewer"
