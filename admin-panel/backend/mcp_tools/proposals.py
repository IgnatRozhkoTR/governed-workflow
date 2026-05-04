"""MCP tools for approval-gated text proposals.

Proposals are read-only text records describing recommended changes. Approval
is a pure status flip — no automatic execution happens. The user reads the
proposal in the admin panel and instructs an agent how to act on it.
"""
from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import TRANSIENT_DB_EXCEPTIONS, mcp, mcp_error, with_global_db, with_mcp_workspace
from services import proposal_service
from services.proposal_service import PROPOSAL_TYPES, ProposalServiceError


_PROPOSAL_TYPE_LITERAL = Literal[
    "memory_write",
    "memory_delete",
    "rule_new",
    "rule_update",
    "agent_new",
    "agent_update",
    "skill_new",
    "skill_update",
    "workflow_improvement",
]

_PROPOSAL_STATUS_LITERAL = Literal[
    "pending", "approved", "rejected", "executed", "failed"
]


def _translate_proposal_error(exc: ProposalServiceError) -> dict:
    if exc.code == "not_found":
        return mcp_error("not_found", str(exc), retryable=False)
    if exc.code in ("invalid_type", "invalid_payload"):
        return mcp_error("validation", str(exc), retryable=False, details=exc.details)
    if exc.code == "invalid_state":
        return mcp_error("business", str(exc), retryable=False, details=exc.details)
    return mcp_error("business", str(exc), retryable=False)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create proposal",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def proposal_create(
    ws,
    project,
    db,
    locale,
    type: Annotated[_PROPOSAL_TYPE_LITERAL, Field(description="Proposal type label. One of: memory_write, memory_delete, rule_new, rule_update, agent_new, agent_update, skill_new, skill_update, workflow_improvement.")],
    title: Annotated[str, Field(description="Short human-readable title shown in the review UI.", min_length=1)],
    body: Annotated[str, Field(description="Markdown body explaining the recommendation. The user reads this and decides whether to act on it.")] = "",
    payload: Annotated[dict, Field(description="Optional structured data as JSON object. Opaque metadata — no schema is enforced.")] = {},
    origin: Annotated[str, Field(description="Free-form origin tag (e.g. 'agent', 'reflection', 'memory_promotion').")] = "agent",
) -> dict:
    """Create a pending text proposal scoped to the current workspace + project.

    Purpose
      Emit a recommended change as text for human review. Approval flips the
      status; nothing is executed automatically. The user instructs an agent
      to perform the recommended action if they want.

    Returns
      Full proposal dict (id, type, status='pending', title, body, payload,
      origin, workspace_id, project_id, created_at, ...).

    Errors
      validation  — type unknown, title empty, payload not a dict.
      transient   — DB failure; caller should retry.
    """
    if type not in PROPOSAL_TYPES:
        return mcp_error("validation", f"Unknown proposal type '{type}'", retryable=False)
    try:
        return proposal_service.create(
            db,
            type=type,
            title=title,
            body=body,
            payload=dict(payload or {}),
            origin=origin,
            workspace_id=ws["id"],
            project_id=project["id"] if project else None,
        )
    except ProposalServiceError as exc:
        return _translate_proposal_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="List proposals",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def proposal_list(
    db,
    status: Annotated[_PROPOSAL_STATUS_LITERAL | None, Field(description="Filter by status. None = all statuses.")] = None,
    type: Annotated[_PROPOSAL_TYPE_LITERAL | None, Field(description="Filter by proposal type label. None = all types.")] = None,
) -> list:
    """List proposals across all workspaces, newest first.

    Returns
      List of proposal dicts.

    Errors
      transient  — DB failure; caller should retry.
    """
    try:
        return proposal_service.list_proposals(db, status=status, type=type)
    except ProposalServiceError as exc:
        return [_translate_proposal_error(exc)]
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return [mcp_error("transient", str(exc), retryable=True)]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get proposal",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def proposal_get(
    db,
    proposal_id: Annotated[int, Field(description="Proposal ID returned by proposal_create or proposal_list.", ge=1)],
) -> dict:
    """Fetch a single proposal by ID.

    Returns
      Full proposal dict including parsed payload.

    Errors
      not_found  — proposal_id does not exist.
      transient  — DB failure; caller should retry.
    """
    try:
        return proposal_service.get(db, proposal_id)
    except ProposalServiceError as exc:
        return _translate_proposal_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Approve proposal",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def proposal_approve(
    db,
    proposal_id: Annotated[int, Field(description="Proposal ID to approve.", ge=1)],
) -> dict:
    """Approve a pending proposal — pure status flip, no execution.

    Purpose
      Approval marks the proposal as reviewed and accepted by the user. Nothing
      runs automatically; the user instructs an agent to act on the proposal
      body if they want. Idempotent: re-approving an approved proposal returns
      the current row.

    Returns
      Updated proposal dict with status='approved'.

    Errors
      not_found  — proposal_id does not exist.
      business   — proposal is in a non-approvable state (e.g. rejected).
      transient  — DB failure; caller should retry.
    """
    try:
        return proposal_service.approve(db, proposal_id)
    except ProposalServiceError as exc:
        return _translate_proposal_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Reject proposal",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def proposal_reject(
    db,
    proposal_id: Annotated[int, Field(description="Proposal ID to reject.", ge=1)],
    reason: Annotated[str, Field(description="Why the proposal was rejected. Surfaced in the audit trail.", min_length=1)],
) -> dict:
    """Reject a pending proposal with a reason. Idempotent against rejected.

    Returns
      Updated proposal dict with status='rejected' and reason set.

    Errors
      not_found  — proposal_id does not exist.
      business   — proposal is in a non-pending state.
      validation — reason is empty.
      transient  — DB failure; caller should retry.
    """
    try:
        return proposal_service.reject(db, proposal_id, reason)
    except ProposalServiceError as exc:
        return _translate_proposal_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Resolve proposal",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def proposal_resolve(
    db,
    proposal_id: Annotated[int, Field(description="Proposal ID to resolve (close out).", ge=1)],
) -> dict:
    """Close out a proposal as rejected. Idempotent against rejected.

    Purpose
      A simple way to clear a proposal that is no longer relevant — useful for
      legacy rows in pre-cleanup states or when the user wants to dismiss a
      proposal without supplying a structured reason.

    Returns
      Updated proposal dict with status='rejected'.

    Errors
      not_found  — proposal_id does not exist.
      transient  — DB failure; caller should retry.
    """
    try:
        return proposal_service.resolve(db, proposal_id)
    except ProposalServiceError as exc:
        return _translate_proposal_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
