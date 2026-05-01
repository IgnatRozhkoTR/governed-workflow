"""MCP tools for generating and retrieving workspace session reflections."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import TRANSIENT_DB_EXCEPTIONS, mcp, mcp_error, with_mcp_workspace
from services import reflection_service
from services.reflection_service import ReflectionServiceError


def _translate_reflection_error(exc: ReflectionServiceError) -> dict:
    if exc.code == "not_found":
        return mcp_error("not_found", str(exc), retryable=False)
    if exc.code == "no_session_found":
        return mcp_error("transient", str(exc), retryable=True)
    if exc.code == "llm_unconfigured":
        return mcp_error("business", str(exc), retryable=False)
    if exc.code == "llm_failure":
        return mcp_error("transient", str(exc), retryable=True)
    return mcp_error("business", str(exc), retryable=False)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Run reflection",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def reflection_run(ws, project, db, locale) -> dict:
    """Generate a reflection for the current workspace's latest session.

    Purpose
      Analyses the Claude Code session transcript and produces a structured
      Markdown report covering what was done, what worked, what did not work,
      and lessons learned. The report is persisted and returned.

    Returns
      {id, workspace_id, content_md, summary, session_id, created_at}

    Errors
      not_found       — workspace not detected for current directory.
      business        — LLM not configured (set OPENAI_API_KEY or ANTHROPIC_API_KEY).
      transient       — no session found yet, or LLM call failed; caller may retry.
    """
    try:
        result = reflection_service.run(db, ws["id"])
        return result
    except ReflectionServiceError as exc:
        return _translate_reflection_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get reflection",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def reflection_get(
    ws,
    project,
    db,
    locale,
    reflection_id: Annotated[int, Field(description="ID of the reflection to fetch.")],
) -> dict:
    """Fetch a single reflection by ID.

    Returns
      {id, workspace_id, content_md, summary, session_id, created_at}

    Errors
      not_found  — reflection ID does not exist.
      transient  — DB failure; caller should retry.
    """
    try:
        return reflection_service.get(db, reflection_id)
    except ReflectionServiceError as exc:
        return _translate_reflection_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="List reflections",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def reflection_list(ws, project, db, locale) -> list:
    """List all reflections for the current workspace, newest first.

    Returns
      List of {id, workspace_id, content_md, summary, session_id, created_at}.
      Empty list when no reflections exist.

    Errors
      not_found  — workspace not detected for current directory.
      transient  — DB failure; caller should retry.
    """
    try:
        return reflection_service.list_reflections(db, ws["id"])
    except ReflectionServiceError as exc:
        return [_translate_reflection_error(exc)]
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return [mcp_error("transient", str(exc), retryable=True)]
