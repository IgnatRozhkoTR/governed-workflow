"""Tests for the reflection service.

The service shells out to ``claude -p`` via ``spawn_claude_agent``. These
tests monkey-patch that helper so no real subprocess is ever launched.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from core.db import get_db, get_db_ctx
from services import reflection_service
from services.proposal_service import create_proposal
from services.reflection_context import ReflectionContext


def _drop_status(workspace_id: int) -> None:
    reflection_service._STATUS.pop(workspace_id, None)


def _build_ctx(
    *,
    workspace_id: int = 1,
    project_id: int = 1,
    branch: str = "feature/x",
    base_branch: str = "main",
    scope: dict | None = None,
    branch_diff: str = "diff --git a/x.py b/x.py\n+added line",
    review_findings: list[dict] | None = None,
    transcript: list[dict] | None = None,
    transcript_truncated: bool = False,
) -> ReflectionContext:
    return ReflectionContext(
        workspace_id=workspace_id,
        project_id=project_id,
        branch=branch,
        base_branch=base_branch,
        scope=scope if scope is not None else {"3.1": {"must": ["x.py"], "may": []}},
        branch_diff=branch_diff,
        review_findings=review_findings if review_findings is not None else [],
        transcript=transcript if transcript is not None else [],
        transcript_truncated=transcript_truncated,
    )


# ── Prompt builder ────────────────────────────────────────────────────────────


def test_build_prompt_includes_all_four_section_headers():
    ctx = _build_ctx()

    prompt = reflection_service._build_prompt(ctx)

    assert "## Ticket scope" in prompt
    assert "## Branch diff (against main)" in prompt
    assert "## Review findings" in prompt
    assert "## Session transcript" in prompt


def test_build_prompt_includes_truncation_notice_when_flagged():
    ctx = _build_ctx(
        transcript=[{"role": "user", "text": "hi", "is_sub_agent": False, "agent_label": None}],
        transcript_truncated=True,
    )

    prompt = reflection_service._build_prompt(ctx)

    assert "transcript truncated to most-recent messages" in prompt


def test_build_prompt_omits_truncation_notice_when_not_flagged():
    ctx = _build_ctx(transcript_truncated=False)

    prompt = reflection_service._build_prompt(ctx)

    assert "transcript truncated" not in prompt


def test_build_prompt_uses_no_diff_placeholder_when_branch_diff_empty():
    ctx = _build_ctx(branch_diff="")

    prompt = reflection_service._build_prompt(ctx)

    assert "_(no diff available)_" in prompt


def test_build_prompt_uses_no_scope_placeholder_when_scope_empty():
    ctx = _build_ctx(scope={})

    prompt = reflection_service._build_prompt(ctx)

    assert "_(no scope recorded)_" in prompt


def test_build_prompt_renders_review_findings_with_severity_prefix():
    findings = [
        {
            "file_path": "src/a.py",
            "line_start": 10,
            "description": "[critical/security] sql injection in handler",
        },
        {
            "file_path": "src/b.py",
            "line_start": 5,
            "description": "[major/logic] off-by-one",
        },
    ]
    ctx = _build_ctx(review_findings=findings)

    prompt = reflection_service._build_prompt(ctx)

    assert "- [critical] src/a.py:10 — sql injection in handler" in prompt
    assert "- [major] src/b.py:5 — off-by-one" in prompt


def test_build_prompt_truncates_long_finding_body():
    long_text = "x" * 1000
    findings = [
        {
            "file_path": "src/a.py",
            "line_start": 1,
            "description": f"[major/logic] {long_text}",
        }
    ]
    ctx = _build_ctx(review_findings=findings)

    prompt = reflection_service._build_prompt(ctx)

    assert "x" * reflection_service._FINDING_BODY_LIMIT in prompt
    assert "x" * (reflection_service._FINDING_BODY_LIMIT + 1) not in prompt


def test_build_prompt_uses_no_findings_placeholder_when_empty():
    ctx = _build_ctx(review_findings=[])

    prompt = reflection_service._build_prompt(ctx)

    assert "_(no review findings)_" in prompt


def test_build_prompt_renders_sub_agent_messages_with_label():
    transcript = [
        {"role": "user", "text": "Plan the work", "is_sub_agent": False, "agent_label": None},
        {
            "role": "assistant",
            "text": "Delegating to reviewer",
            "is_sub_agent": True,
            "agent_label": "architecture-reviewer",
        },
    ]
    ctx = _build_ctx(transcript=transcript)

    prompt = reflection_service._build_prompt(ctx)

    assert "**user**: Plan the work" in prompt
    assert "**assistant(sub_agent:architecture-reviewer)**: Delegating to reviewer" in prompt


def test_build_prompt_truncates_long_transcript_messages():
    long_text = "y" * 5000
    transcript = [
        {"role": "user", "text": long_text, "is_sub_agent": False, "agent_label": None}
    ]
    ctx = _build_ctx(transcript=transcript)

    prompt = reflection_service._build_prompt(ctx)

    assert "y" * reflection_service._TRANSCRIPT_TEXT_LIMIT in prompt
    assert "y" * (reflection_service._TRANSCRIPT_TEXT_LIMIT + 1) not in prompt


# ── Timeout env var ───────────────────────────────────────────────────────────


def test_timeout_s_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("REFLECTION_TIMEOUT_S", raising=False)

    assert reflection_service._timeout_s() == reflection_service._DEFAULT_TIMEOUT_S


def test_timeout_s_reads_env_var_when_set(monkeypatch):
    monkeypatch.setenv("REFLECTION_TIMEOUT_S", "120")

    assert reflection_service._timeout_s() == 120.0


def test_timeout_s_falls_back_when_env_var_invalid(monkeypatch):
    monkeypatch.setenv("REFLECTION_TIMEOUT_S", "not-a-number")

    assert reflection_service._timeout_s() == reflection_service._DEFAULT_TIMEOUT_S


# ── Status accessor ───────────────────────────────────────────────────────────


def test_get_status_returns_idle_entry_when_workspace_never_run():
    status = reflection_service.get_status(999_999)

    assert status.workspace_id == 999_999
    assert status.state == "idle"
    assert status.started_at is None
    assert status.finished_at is None
    assert status.proposals_before == 0
    assert status.proposals_after == 0
    assert status.error is None


# ── run_reflection orchestration ──────────────────────────────────────────────


def test_run_reflection_marks_status_succeeded_when_agent_returns(workspace, monkeypatch):
    captured: list[str] = []

    async def fake_spawn(*, agent, prompt, project_path, max_turns, timeout_s, suppress_mcp=False):
        captured.append(agent)
        return '{"result": "ok"}'

    monkeypatch.setattr(
        "services.reflection_service.spawn_claude_agent", fake_spawn
    )

    try:
        result = asyncio.run(
            reflection_service.run_reflection(
                get_db_ctx, workspace["id"], Path(workspace["working_dir"])
            )
        )

        assert result.state == "succeeded"
        assert result.started_at is not None
        assert result.finished_at is not None
        assert result.error is None
        assert result.agent_stdout_tail == '{"result": "ok"}'
        assert captured == ["reflector"]
        assert reflection_service.get_status(workspace["id"]).state == "succeeded"
    finally:
        _drop_status(workspace["id"])


def test_run_reflection_marks_status_failed_when_agent_raises(workspace, monkeypatch):
    async def fake_spawn(*, agent, prompt, project_path, max_turns, timeout_s, suppress_mcp=False):
        raise RuntimeError("reflector exit 1: boom")

    monkeypatch.setattr(
        "services.reflection_service.spawn_claude_agent", fake_spawn
    )

    try:
        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(
                reflection_service.run_reflection(
                    get_db_ctx, workspace["id"], Path(workspace["working_dir"])
                )
            )

        assert "boom" in str(exc_info.value)
        status = reflection_service.get_status(workspace["id"])
        assert status.state == "failed"
        assert status.error is not None
        assert "boom" in status.error
        assert status.finished_at is not None
    finally:
        _drop_status(workspace["id"])


def test_run_reflection_counts_proposals_before_and_after(workspace, monkeypatch):
    db = get_db()
    try:
        create_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=workspace["project_id"],
            type="rule_new",
            implementation_kind="auto",
            title="Pre-existing",
            body="Was already here",
        )
    finally:
        db.close()

    async def fake_spawn(*, agent, prompt, project_path, max_turns, timeout_s, suppress_mcp=False):
        agent_db = get_db()
        try:
            create_proposal(
                agent_db,
                workspace_id=workspace["id"],
                project_id=workspace["project_id"],
                type="memory_write",
                implementation_kind="auto",
                title="From the reflector",
                body="Submitted via MCP",
            )
        finally:
            agent_db.close()
        return '{"result": "submitted"}'

    monkeypatch.setattr(
        "services.reflection_service.spawn_claude_agent", fake_spawn
    )

    try:
        result = asyncio.run(
            reflection_service.run_reflection(
                get_db_ctx, workspace["id"], Path(workspace["working_dir"])
            )
        )

        assert result.proposals_before == 1
        assert result.proposals_after == 2
    finally:
        _drop_status(workspace["id"])


def test_run_reflection_raises_when_workspace_missing(monkeypatch, clean_db):
    async def fake_spawn(*, agent, prompt, project_path, max_turns, timeout_s, suppress_mcp=False):
        return '{"result": "should not run"}'

    monkeypatch.setattr(
        "services.reflection_service.spawn_claude_agent", fake_spawn
    )

    try:
        with pytest.raises(reflection_service.ReflectionServiceError) as exc_info:
            asyncio.run(
                reflection_service.run_reflection(
                    get_db_ctx, 424242, Path("/tmp")
                )
            )

        assert exc_info.value.code == "workspace_not_found"
        assert reflection_service.get_status(424242).state == "failed"
    finally:
        _drop_status(424242)


# ── list_proposals_for_workspace ──────────────────────────────────────────────


def test_list_proposals_for_workspace_returns_proposals(workspace):
    db = get_db()
    try:
        create_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=workspace["project_id"],
            type="rule_new",
            implementation_kind="auto",
            title="A rule",
            body="Body",
        )
        rows = reflection_service.list_proposals_for_workspace(db, workspace["id"])
    finally:
        db.close()

    assert len(rows) == 1
    assert rows[0]["title"] == "A rule"


def test_list_proposals_for_workspace_returns_empty_when_none(workspace):
    db = get_db()
    try:
        rows = reflection_service.list_proposals_for_workspace(db, workspace["id"])
    finally:
        db.close()

    assert rows == []
