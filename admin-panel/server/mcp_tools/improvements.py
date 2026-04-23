from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import mcp, with_global_db, mcp_error
from core.i18n import t
from services import improvement_service

_VALID_SCOPES = ("workflow", "project", "skill", "tooling", "documentation")
_VALID_STATUSES = ("open", "resolved")


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
        title="Report improvement",
    )
)
@with_global_db
def workspace_report_improvement(
    db,
    scope: Annotated[
        Literal["workflow", "project", "skill", "tooling", "documentation"],
        Field(description="Category of improvement: workflow, project, skill, tooling, or documentation."),
    ],
    title: Annotated[str, Field(description="Short summary of the improvement.", min_length=1, max_length=200)],
    description: Annotated[str, Field(description="Detailed description of what should be improved and how.")] = "",
    context: Annotated[str, Field(description="Optional: what happened that led to this discovery.")] = "",
) -> dict:
    """Report a potential improvement discovered during work.

    Purpose
      NOT workspace-bound — callable from any directory. Use when you discover
      something that could be done better in future workflows: a correct
      build/test invocation found through trial and error, a workflow pattern
      that failed (e.g. teammate agent going idle), a missing skill or
      documentation gap, or a tool configuration worth saving for reuse.

    Parameters
      scope:       Category — workflow, project, skill, tooling, or documentation.
      title:       Short summary (max 200 chars).
      description: Full description of what to improve and how.
      context:     Optional — what triggered this discovery.

    Returns
      {ok: True, id: <int>} on success.

    Errors
      errorCategory values used:
        - validation   scope not in allowed set, or title/description blank.
        - transient    DB failure; caller should retry.
    """
    if not title.strip():
        return mcp_error("validation", t("mcp.error.titleRequired"), retryable=False)
    if not description.strip():
        return mcp_error("validation", t("mcp.error.descriptionRequired"), retryable=False)

    result = improvement_service.report_improvement(
        db, scope, title, description, context=context or None
    )
    db.commit()
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
        title="Get improvements",
    )
)
@with_global_db
def workspace_get_improvements(
    db,
    scope: Annotated[
        str,
        Field(description="Filter by scope (workflow, project, skill, tooling, documentation). Empty = all."),
    ] = "",
    status: Annotated[
        str,
        Field(description="Filter by status (open, resolved). Empty = all."),
    ] = "",
) -> list:
    """List reported improvements, optionally filtered.

    Purpose
      NOT workspace-bound — callable from any directory. Returns all recorded
      improvement suggestions, optionally narrowed by scope and/or status.

    Parameters
      scope:  One of workflow, project, skill, tooling, documentation. Empty = all.
      status: One of open, resolved. Empty = all.

    Returns
      List of improvement objects: id, scope, title, description, context,
      status, created_at. Empty list when no matches (not an error).
    """
    return improvement_service.get_improvements(
        db, scope=scope or None, status=status or None
    )
