"""Reflection pass: spawn a ``reflector`` sub-agent with workspace context.

The reflector reviews the just-finished ticket (scope, branch diff, review
findings, session transcript) and submits change proposals to the panel via
the ``workspace_submit_proposal`` MCP tool. Proposals capture concrete
improvements: memory notes, new/updated rules, new/updated agents or skills,
or higher-level workflow changes.

The agent does the writes itself through MCP. This service just composes the
prompt, runs the subprocess, and reports a status summary by counting how
many rows landed in ``proposals`` for the workspace before/after the run.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, ContextManager, Literal

from services._claude_runner import spawn_claude_agent
from services import proposal_service
from services.reflection_context import (
    ReflectionContext,
    gather_reflection_context,
)


log = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_S = 1800.0
_TIMEOUT_ENV_VAR = "REFLECTION_TIMEOUT_S"

_REFLECTOR_AGENT = "reflector"

_TRANSCRIPT_TEXT_LIMIT = 1500
_FINDING_BODY_LIMIT = 400
_STDOUT_TAIL_CHARS = 2000

# Review finding descriptions are written as "[severity/type] summary" by the
# file-reviewer pipeline. We pull the leading bracket so the reflector sees
# severity as a first-class label without re-parsing the body.
_SEVERITY_PREFIX_RE = re.compile(r"^\[([^/\]]+)(?:/[^\]]*)?\]\s*(.*)$", re.DOTALL)


ReflectionState = Literal["idle", "running", "succeeded", "failed"]

# Callable returning a context manager that yields a fresh DB connection.
# Mirrors core.db.get_db_ctx so background work doesn't share the request
# connection (sqlite handles are per-thread).
DbFactory = Callable[[], ContextManager]


@dataclass
class ReflectionStatus:
    workspace_id: int
    state: ReflectionState = "idle"
    started_at: str | None = None
    finished_at: str | None = None
    proposals_before: int = 0
    proposals_after: int = 0
    error: str | None = None
    agent_stdout_tail: str | None = None


class ReflectionServiceError(Exception):
    """Domain error for reflection service operations."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


_STATUS: dict[int, ReflectionStatus] = {}


def get_status(workspace_id: int) -> ReflectionStatus:
    existing = _STATUS.get(workspace_id)
    if existing is not None:
        return existing
    return ReflectionStatus(workspace_id=workspace_id, state="idle")


def list_proposals_for_workspace(db, workspace_id: int) -> list[dict]:
    return proposal_service.list_proposals(db, workspace_id=workspace_id)


def _timeout_s() -> float:
    raw = os.environ.get(_TIMEOUT_ENV_VAR)
    if raw is None:
        return _DEFAULT_TIMEOUT_S
    try:
        parsed = float(raw)
    except ValueError:
        log.warning("invalid %s=%r; using default", _TIMEOUT_ENV_VAR, raw)
        return _DEFAULT_TIMEOUT_S
    return parsed if parsed > 0 else _DEFAULT_TIMEOUT_S


async def run_reflection(
    db_factory: DbFactory,
    workspace_id: int,
    project_path: Path,
) -> ReflectionStatus:
    """Run one reflection pass for ``workspace_id``.

    Steps:
        1. Mark status running.
        2. Open a fresh DB connection, load the workspace, gather context,
           count proposals_before.
        3. Compose the agent prompt and spawn ``reflector``.
        4. Reopen a connection (the agent may have inserted via MCP),
           count proposals_after.
        5. Update status with result; on failure record the error and re-raise.
    """
    status = _begin(workspace_id)

    try:
        ctx, proposals_before = _load_context_and_count(db_factory, workspace_id)
        prompt = _build_prompt(ctx)
        stdout = await spawn_claude_agent(
            agent=_REFLECTOR_AGENT,
            prompt=prompt,
            project_path=project_path,
            max_turns=None,
            timeout_s=_timeout_s(),
        )
        proposals_after = _count_proposals(db_factory, workspace_id)
    except Exception as exc:
        _mark_failed(status, exc)
        raise

    _mark_succeeded(status, proposals_before, proposals_after, stdout)
    return status


def _begin(workspace_id: int) -> ReflectionStatus:
    status = ReflectionStatus(
        workspace_id=workspace_id,
        state="running",
        started_at=datetime.now().isoformat(),
    )
    _STATUS[workspace_id] = status
    return status


def _load_context_and_count(
    db_factory: DbFactory, workspace_id: int
) -> tuple[ReflectionContext, int]:
    with db_factory() as db:
        ws = db.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        if ws is None:
            raise ReflectionServiceError(
                code="workspace_not_found",
                message=f"workspace {workspace_id} does not exist",
            )
        project_row = db.execute(
            "SELECT path FROM projects WHERE id = ?", (ws["project_id"],)
        ).fetchone()
        if project_row is None:
            raise ReflectionServiceError(
                code="project_not_found",
                message=f"project {ws['project_id']} does not exist",
            )
        ctx = gather_reflection_context(
            db, ws, project_path=Path(project_row["path"])
        )
        proposals_before = _count_proposals_on(db, workspace_id)
    return ctx, proposals_before


def _count_proposals(db_factory: DbFactory, workspace_id: int) -> int:
    with db_factory() as db:
        return _count_proposals_on(db, workspace_id)


def _count_proposals_on(db, workspace_id: int) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS n FROM proposals WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def _mark_succeeded(
    status: ReflectionStatus,
    proposals_before: int,
    proposals_after: int,
    stdout: str,
) -> None:
    status.state = "succeeded"
    status.finished_at = datetime.now().isoformat()
    status.proposals_before = proposals_before
    status.proposals_after = proposals_after
    status.agent_stdout_tail = _tail(stdout)


def _mark_failed(status: ReflectionStatus, exc: BaseException) -> None:
    status.state = "failed"
    status.finished_at = datetime.now().isoformat()
    status.error = str(exc) or exc.__class__.__name__


def _tail(text: str) -> str | None:
    if not text:
        return None
    if len(text) <= _STDOUT_TAIL_CHARS:
        return text
    return text[-_STDOUT_TAIL_CHARS:]


# ── Prompt composition ────────────────────────────────────────────────────────


_PROMPT_TEMPLATE = """\
You are the **reflector** for the just-finished ticket on branch `{branch}` (base `{base_branch}`).

Your job: review the ticket's outcome and submit proposals — one at a time — via the `mcp__governed-workflow__workspace_submit_proposal` MCP tool. Each proposal captures a concrete improvement we should make to this workflow itself: a new or updated rule, a memory note, a new or updated agent or skill, or a higher-level workflow improvement.

Submit only proposals supported by concrete evidence from the materials below. No speculation. Better to submit fewer high-quality proposals than many weak ones.

For each proposal:
- Set `implementation_kind='auto'` for proposals the panel can apply directly: `memory_write`, `memory_delete`, `rule_new`, `rule_update`.
- Set `implementation_kind='manual'` for proposals the orchestrator will pick up later: `agent_new`, `agent_update`, `skill_new`, `skill_update`, `workflow_improvement`.
- `payload_json` should carry the structured content the implementer needs (rule body, memory note text, agent diff sketch).

## Ticket scope

{scope_block}

## Branch diff (against {base_branch})

{branch_diff_block}

## Review findings

{review_findings_block}

## Session transcript

{transcript_block}
{truncation_notice}

When you've submitted every supported proposal, stop. Do not summarize.
"""


def _build_prompt(ctx: ReflectionContext) -> str:
    return _PROMPT_TEMPLATE.format(
        branch=ctx.branch,
        base_branch=ctx.base_branch,
        scope_block=_render_scope(ctx.scope),
        branch_diff_block=_render_branch_diff(ctx.branch_diff),
        review_findings_block=_render_review_findings(ctx.review_findings),
        transcript_block=_render_transcript(ctx.transcript),
        truncation_notice=_render_truncation_notice(ctx.transcript_truncated),
    )


def _render_scope(scope: dict) -> str:
    if not scope:
        return "_(no scope recorded)_"
    return json.dumps(scope, indent=2)


def _render_branch_diff(branch_diff: str) -> str:
    if not branch_diff.strip():
        return "_(no diff available)_"
    return branch_diff


def _render_review_findings(findings: list[dict]) -> str:
    if not findings:
        return "_(no review findings)_"
    return "\n".join(_render_one_finding(f) for f in findings)


def _render_one_finding(finding: dict) -> str:
    description = (finding.get("description") or "").strip()
    severity, body = _split_severity(description)
    title = _finding_title(finding)
    truncated_body = body[:_FINDING_BODY_LIMIT]
    return f"- [{severity}] {title} — {truncated_body}"


def _split_severity(description: str) -> tuple[str, str]:
    match = _SEVERITY_PREFIX_RE.match(description)
    if match is None:
        return "unspecified", description
    return match.group(1).strip() or "unspecified", match.group(2).strip()


def _finding_title(finding: dict) -> str:
    file_path = finding.get("file_path") or "(unknown file)"
    line = finding.get("line_start")
    if line:
        return f"{file_path}:{line}"
    return file_path


def _render_transcript(transcript: list[dict]) -> str:
    if not transcript:
        return "_(no transcript)_"
    return "\n---\n".join(_render_one_message(m) for m in transcript)


def _render_one_message(message: dict) -> str:
    role = message.get("role", "unknown")
    text = (message.get("text") or "")[:_TRANSCRIPT_TEXT_LIMIT]
    if message.get("is_sub_agent") and message.get("agent_label"):
        header = f"**{role}(sub_agent:{message['agent_label']})**"
    else:
        header = f"**{role}**"
    return f"{header}: {text}"


def _render_truncation_notice(truncated: bool) -> str:
    if truncated:
        return "\n\n_Note: transcript truncated to most-recent messages._"
    return ""
