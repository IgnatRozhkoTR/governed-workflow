import json
from typing import Annotated, Literal

from pydantic import Field
from mcp.types import ToolAnnotations

from mcp_tools import mcp, with_mcp_workspace, mcp_error
from services import proposal_service
from services.proposal_service import ProposalServiceError

_VALID_TYPES = frozenset({
    "memory_write", "memory_delete",
    "rule_new", "rule_update",
    "agent_new", "agent_update",
    "skill_new", "skill_update",
    "workflow_improvement",
})

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
    implementation_kind: Annotated[Literal["auto", "manual"], Field(description="'auto' = the panel applies this proposal directly when approved. 'manual' = the orchestrator picks it up and runs a sub-agent to implement it. Memory writes / rule changes are auto; agent / skill / workflow proposals are manual.")],
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
