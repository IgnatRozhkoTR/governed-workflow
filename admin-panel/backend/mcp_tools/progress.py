import json
from typing import Annotated, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import TRANSIENT_DB_EXCEPTIONS, mcp, with_mcp_workspace, mcp_error
from core.i18n import t
from services import progress_service


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update phase progress",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def workspace_update_progress(
    ws,
    project,
    db,
    locale,
    phase: Annotated[
        str,
        Field(description="Phase key like '1.0', '1', '2', '3.1', '4'."),
    ],
    summary: Annotated[
        str,
        Field(
            description="1-3 sentence concise summary. Must be non-empty for phase gate validation.",
            min_length=1,
        ),
    ],
    details: Annotated[
        Optional[dict],
        Field(
            description=(
                "Structured record with fields like actions, obstacles, decisions, findings, "
                "files_changed, agents_deployed, outcome. All optional."
            )
        ),
    ] = None,
) -> dict:
    """Update progress for a phase. Upserts — same phase key overwrites the existing entry.

    Purpose
      Called by the orchestrator after completing phase work. The entry is used for:
      phase gate validation (summary must be non-empty to advance), session recovery
      after compaction (details reconstructs what happened), and daily reflection queries
      (entries are date-stamped). Calling with the same phase key is a no-op upsert.

    Parameters
      phase:   Phase key, e.g. '1.0', '1', '2', '3.1', '4'.
      summary: 1-3 sentence summary of what was done (required for gate validation).
      details: Optional rich record — any subset of {actions, obstacles, decisions,
               findings, files_changed, agents_deployed, outcome}.

    Returns
      {ok: True, phase: <key>}

    Errors
      validation — phase or summary is empty/blank.
      not_found  — no workspace detected for current directory.
      transient  — DB failure; caller should retry.

    Example
      workspace_update_progress(phase="1.0", summary="Completed initial assessment.")
      workspace_update_progress(phase="3.1", summary="Refactored service layer.",
          details={"files_changed": ["src/Service.java"], "outcome": "All tests green"})
    """
    if not phase or not phase.strip():
        return mcp_error("validation", t("mcp.error.phaseRequired", locale), retryable=False)
    if not summary or not summary.strip():
        return mcp_error("validation", t("mcp.error.summaryRequired", locale), retryable=False)

    details_json = json.dumps(details) if details else None

    try:
        result = progress_service.update_progress(db, ws["id"], phase.strip(), summary.strip(), details_json)
        db.commit()
        return result
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get phase progress",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def workspace_get_progress(
    ws,
    project,
    db,
    locale,
    phase: Annotated[
        str,
        Field(description="Specific phase key to fetch. Empty string returns all."),
    ] = "",
) -> dict:
    """Get progress entries with full details. Optionally filter by phase key.

    Purpose
      Returns persisted progress records for the workspace. An empty result dict
      means no progress has been recorded yet — not an error. Use
      workspace_update_progress to record phase work. Prefer this tool over
      workspace_get_state when you need full details and timestamps.

    Parameters
      phase: Phase key, e.g. '1.0', '2'. Empty string = return all phases.

    Returns
      Dict of phase → {summary, details?, created_at, updated_at}.
      Empty dict {} when no entries match (successful query, no data).

    Errors
      not_found  — no workspace detected for current directory.
      transient  — DB failure; caller should retry.

    Example
      workspace_get_progress()
      workspace_get_progress(phase="3.1")
    """
    try:
        return progress_service.get_progress(db, ws["id"], phase_key=phase or None)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set impact analysis",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def workspace_set_impact_analysis(
    ws,
    project,
    db,
    locale,
    affected_flows: Annotated[
        str,
        Field(description="Which user flows or interactions are affected by this change."),
    ] = "",
    api_changes: Annotated[
        str,
        Field(description="API endpoint changes: new, modified, or removed endpoints and contract changes."),
    ] = "",
    data_flow_changes: Annotated[
        str,
        Field(description="Where key values come from and how data moves through the system."),
    ] = "",
    external_dependencies: Annotated[
        str,
        Field(description="DB migrations, infrastructure changes, or required coordination with other teams."),
    ] = "",
    ticket_gaps: Annotated[
        str,
        Field(description="What the ticket leaves ambiguous or underspecified."),
    ] = "",
    open_questions: Annotated[
        str,
        Field(description="Questions that need user input and cannot be resolved from code or web research."),
    ] = "",
) -> dict:
    """Save structured impact analysis for the workspace. Called during phase 1.3.

    Purpose
      Replaces any previously saved impact analysis — calling twice with different
      fields records the latest values only. All fields are optional; omit any that
      are not applicable to the current ticket.

    Parameters
      affected_flows:       User flows/interactions impacted.
      api_changes:          Endpoint additions, modifications, removals, and contract changes.
      data_flow_changes:    Data origin, transformation, and routing through the system.
      external_dependencies: DB migrations, infra changes, cross-team coordination.
      ticket_gaps:          Ambiguities or underspecified requirements in the ticket.
      open_questions:       Questions that require user input to resolve.

    Returns
      {ok: True}

    Errors
      not_found  — no workspace detected for current directory.
      transient  — DB failure; caller should retry.

    Example
      workspace_set_impact_analysis(
          affected_flows="Trade booking flow and position calculation.",
          ticket_gaps="Ticket does not specify currency rounding strategy.")
    """
    analysis = {
        "affected_flows": affected_flows,
        "api_changes": api_changes,
        "data_flow_changes": data_flow_changes,
        "external_dependencies": external_dependencies,
        "ticket_gaps": ticket_gaps,
        "open_questions": open_questions,
    }

    try:
        progress_service.set_impact_analysis(db, ws["id"], analysis)
        db.commit()
        return {"ok": True}
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
