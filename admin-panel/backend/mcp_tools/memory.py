"""MCP tools for workspace memory (save, retrieve, get, delete, list)."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import TRANSIENT_DB_EXCEPTIONS, mcp, mcp_error, with_mcp_workspace
from services import memory_service
from services.memory_provider import MemoryProviderError


def _translate_memory_error(exc: MemoryProviderError) -> dict:
    if exc.code == "provider_unavailable":
        return mcp_error(
            "business",
            str(exc),
            retryable=False,
            details={"hint": "enable the mempalace module via the Setup page"},
        )
    if exc.code == "memory_not_found":
        return mcp_error("not_found", str(exc), retryable=False)
    if exc.code in ("invalid_scope", "invalid_input"):
        return mcp_error("validation", str(exc), retryable=False)
    return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Save memory",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def memory_save(
    ws,
    project,
    db,
    locale,
    content: Annotated[str, Field(description="The text content to remember. Must be non-empty.")],
    scope: Annotated[dict, Field(description="Scope for the memory. Shape: {kind: 'project'|'ticket', project_id?: str, workspace_id?: int}. Additional fields allowed.")],
    metadata: Annotated[dict, Field(description="Arbitrary key-value metadata attached to the memory.")] = {},
) -> dict:
    """Persist a piece of information into the memory store.

    Purpose
      Store any text content tagged with a scope so it can be retrieved later
      across sessions. Scope determines the wing/room in MemPalace.

    Returns
      {memory_id, content, scope, metadata, created_at}

    Errors
      business    — mempalace module not enabled (provider_unavailable).
      validation  — content empty or scope malformed.
      transient   — temporary storage failure; caller may retry.
    """
    try:
        return memory_service.save(content, scope, metadata)
    except MemoryProviderError as exc:
        return _translate_memory_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Retrieve memories",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def memory_retrieve(
    ws,
    project,
    db,
    locale,
    query: Annotated[str, Field(description="Natural-language search query used for semantic retrieval.")],
    scope_filter: Annotated[list[dict] | None, Field(description="Optional list of scope dicts to restrict the search. Each entry has the same shape as 'scope' in memory_save.")] = None,
    limit: Annotated[int, Field(description="Maximum number of results to return. Default 10.", ge=1)] = 10,
) -> list:
    """Semantic search over stored memories.

    Returns
      List of {memory_id, content, scope, metadata, score, created_at}.
      Empty list when nothing matches.

    Errors
      business    — mempalace module not enabled.
      validation  — query empty or limit invalid.
      transient   — temporary failure; caller may retry.
    """
    try:
        return memory_service.retrieve(query, scope_filter, limit)
    except MemoryProviderError as exc:
        return [_translate_memory_error(exc)]
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return [mcp_error("transient", str(exc), retryable=True)]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get memory",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def memory_get(
    ws,
    project,
    db,
    locale,
    memory_id: Annotated[str, Field(description="Unique memory identifier returned by memory_save.")],
) -> dict:
    """Fetch a single memory by its ID.

    Returns
      {memory_id, content, scope, metadata, created_at}

    Errors
      not_found   — memory_id does not exist.
      business    — mempalace module not enabled.
      transient   — DB failure; caller should retry.
    """
    try:
        return memory_service.get(memory_id)
    except MemoryProviderError as exc:
        return _translate_memory_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete memory",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=True,
    )
)
@with_mcp_workspace
def memory_delete(
    ws,
    project,
    db,
    locale,
    memory_id: Annotated[str, Field(description="Unique memory identifier to remove.")],
) -> dict:
    """Permanently delete a memory by ID.

    Returns
      {ok: True, deleted_id: str}

    Errors
      not_found   — memory_id does not exist.
      business    — mempalace module not enabled.
      transient   — temporary failure; caller may retry.
    """
    try:
        memory_service.delete(memory_id)
    except MemoryProviderError as exc:
        return _translate_memory_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
    return {"ok": True, "deleted_id": memory_id}


@mcp.tool(
    annotations=ToolAnnotations(
        title="List memories",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def memory_list(
    ws,
    project,
    db,
    locale,
    scope_filter: Annotated[list[dict] | None, Field(description="Optional list of scope dicts to filter results. Each entry has the same shape as 'scope' in memory_save.")] = None,
) -> list:
    """List all stored memories, optionally filtered by scope.

    Returns
      List of {memory_id, content, scope, metadata, created_at}.
      Empty list when the store is empty or no entries match the filter.

    Errors
      business    — mempalace module not enabled.
      transient   — temporary failure; caller may retry.
    """
    try:
        return memory_service.list_memories(scope_filter)
    except MemoryProviderError as exc:
        return [_translate_memory_error(exc)]
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return [mcp_error("transient", str(exc), retryable=True)]
