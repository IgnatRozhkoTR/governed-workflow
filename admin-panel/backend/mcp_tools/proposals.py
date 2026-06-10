import dataclasses
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from mcp.types import ToolAnnotations

from mcp_tools import mcp, with_mcp_workspace, mcp_error
from services import proposal_service
from services.proposal_service import (
    ALLOWED_STATUSES as _VALID_STATUSES,
    ALLOWED_TYPES as _VALID_TYPES,
    ProposalServiceError,
)
from services.reflection_context import gather_reflection_context

_VALID_IMPLEMENTATION_KINDS = frozenset({"auto", "manual"})

_SERVICE_ERROR_TO_CATEGORY = {
    "invalid_proposal_type": ("validation", False),
    "invalid_implementation_kind": ("validation", False),
}


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    idempotentHint=False,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_submit_proposal(
    ws, project, db, locale,
    type: Annotated[Literal["memory_write", "memory_delete", "rule_new", "rule_update", "agent_new", "agent_update", "skill_new", "skill_update", "workflow_improvement"], Field(description="The kind of change being proposed.")],
    implementation_kind: Annotated[Literal["auto", "manual"], Field(description="'auto' = the orchestrator applies it directly during phase 5.1. 'manual' = the orchestrator picks it up and runs a sub-agent to implement it. Memory writes / rule changes are auto; agent / skill / workflow proposals are manual.")],
    title: Annotated[str, Field(description="One-line summary of the proposal.")],
    body: Annotated[str, Field(description="Markdown body — the rationale, the suggested content, the affected scope.")],
    payload_json: Annotated[str | None, Field(description="Optional JSON-encoded structured payload (e.g. the rule content, the memory note, the agent diff). Pass a JSON string, not an object.")] = None,
    reason: Annotated[str | None, Field(description="Optional short reason — references to the session, the diff, the review finding, etc.")] = None,
) -> dict:
    """Submit a single change proposal from the reflection agent.

    Purpose:
        Records a structured proposal for a workspace improvement. The panel
        queues it for human review; auto-kind proposals are applied directly
        on approval, manual-kind proposals spawn a sub-agent.

    Parameters:
        type: Category of change (memory_write, rule_new, agent_update, etc.).
        implementation_kind: 'auto' for panel-applied changes, 'manual' for
            sub-agent implementation.
        title: Single-line summary shown in the panel.
        body: Markdown rationale and detail.
        payload_json: Optional JSON string with structured change content.
        reason: Optional reference to session, diff, or review finding.

    Returns:
        {"id": <int>, "status": "proposed"} on success.

    Errors:
        invalid_argument — unknown type, unknown implementation_kind, or
            payload_json is not valid JSON.

    Example:
        workspace_submit_proposal(
            type="rule_new",
            implementation_kind="manual",
            title="Add rate-limiting rule",
            body="Observed repeated API calls without backoff...",
        )
    """
    if type not in _VALID_TYPES:
        return mcp_error(
            "validation",
            f"Unknown proposal type: {type!r}. Allowed: {sorted(_VALID_TYPES)}",
            retryable=False,
            details={"type": type},
        )

    if implementation_kind not in _VALID_IMPLEMENTATION_KINDS:
        return mcp_error(
            "validation",
            f"Unknown implementation_kind: {implementation_kind!r}. Allowed: {sorted(_VALID_IMPLEMENTATION_KINDS)}",
            retryable=False,
            details={"implementation_kind": implementation_kind},
        )

    if payload_json is not None:
        try:
            json.loads(payload_json)
        except (json.JSONDecodeError, ValueError):
            return mcp_error(
                "validation",
                "payload_json must be valid JSON",
                retryable=False,
                details={"payload_json_preview": payload_json[:120]},
            )

    try:
        proposal_id = proposal_service.create_proposal(
            db,
            workspace_id=ws["id"],
            project_id=ws["project_id"],
            type=type,
            implementation_kind=implementation_kind,
            title=title,
            body=body,
            payload_json=payload_json,
            origin="reflection",
            reason=reason,
        )
    except ProposalServiceError as exc:
        entry = _SERVICE_ERROR_TO_CATEGORY.get(exc.code)
        if entry:
            category, retryable = entry
        else:
            category, retryable = "business", False
        return mcp_error(category, exc.code, retryable=retryable, details={"code": exc.code})

    db.commit()
    return {"id": proposal_id, "status": "proposed"}


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_get_reflection_context(ws, project, db, locale) -> dict:
    """Return the reflection context bundle for this workspace.

    Purpose:
        Provides the four context blobs the reflection agent reads at phase 5.1:
        scope, branch diff, review findings, and session transcript.

    Returns:
        Dict with keys: workspace_id, project_id, branch, base_branch, scope,
        branch_diff, review_findings, transcript, transcript_truncated.
    """
    project_path = Path(project["path"])
    ctx = gather_reflection_context(db, ws, project_path=project_path)
    return dataclasses.asdict(ctx)


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_list_proposals(
    ws,
    project,
    db,
    locale,
    implementation_kind: Annotated[Literal["auto", "manual"] | None, Field(description="Optional filter by implementation kind.")] = None,
    status: Annotated[Literal["proposed", "rejected", "executed", "failed"] | None, Field(description="Optional filter by status.")] = None,
) -> dict:
    """List proposals for this workspace, newest first. Filter optionally by implementation_kind and/or status.

    Returns:
        {"proposals": [...]} where each entry is the full proposal row.
    """
    if implementation_kind is not None and implementation_kind not in _VALID_IMPLEMENTATION_KINDS:
        return mcp_error(
            "validation",
            f"Unknown implementation_kind: {implementation_kind!r}. Allowed: {sorted(_VALID_IMPLEMENTATION_KINDS)}",
            retryable=False,
            details={"implementation_kind": implementation_kind},
        )

    if status is not None and status not in _VALID_STATUSES:
        return mcp_error(
            "validation",
            f"Unknown status: {status!r}. Allowed: {sorted(_VALID_STATUSES)}",
            retryable=False,
            details={"status": status},
        )

    try:
        proposals = proposal_service.list_proposals(
            db,
            workspace_id=ws["id"],
            implementation_kind=implementation_kind,
            status=status,
        )
    except ProposalServiceError as exc:
        return mcp_error("validation", exc.code, retryable=False, details={"code": exc.code})

    return {"proposals": proposals}


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_resolve_proposal(
    ws,
    project,
    db,
    locale,
    proposal_id: Annotated[int, Field(description="The proposal id returned by submit_proposal.")],
    status: Annotated[Literal["executed", "failed", "rejected"], Field(description="The final state of the proposal.")],
    result_json: Annotated[str | None, Field(description="Optional JSON-encoded result blob — e.g. a short summary, the path of the applied file, or the error message.")] = None,
) -> dict:
    """Mark a proposal executed/failed/rejected.

    Parameters:
        proposal_id: The integer id returned by workspace_submit_proposal.
        status: One of executed, failed, or rejected.
        result_json: Optional JSON string with a result summary or error detail.

    Returns:
        The updated proposal row as a dict.

    Errors:
        not_found — proposal_id does not exist or belongs to a different workspace.
        validation — result_json is not valid JSON, or status is invalid.
    """
    if result_json is not None:
        try:
            json.loads(result_json)
        except (json.JSONDecodeError, ValueError):
            return mcp_error(
                "validation",
                "result_json must be valid JSON",
                retryable=False,
                details={"result_json_preview": result_json[:120]},
            )

    existing = proposal_service.get_proposal(db, proposal_id)
    if existing is None or existing["workspace_id"] != ws["id"]:
        return mcp_error(
            "not_found",
            f"proposal {proposal_id} not found in this workspace",
            retryable=False,
            details={"proposal_id": proposal_id},
        )

    try:
        updated = proposal_service.resolve_proposal(
            db,
            proposal_id,
            status=status,
            result_json=result_json,
        )
    except ProposalServiceError as exc:
        return mcp_error("validation", exc.code, retryable=False, details={"code": exc.code})

    db.commit()
    return updated
