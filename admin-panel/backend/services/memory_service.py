"""Thin validation wrapper over the memory provider.

Validates inputs before delegating to the provider returned by
mempalace_adapter.get_provider(). MemoryProviderError codes pass through
unchanged so callers (routes, MCP tools) can map them consistently.
"""
from services import mempalace_adapter
from services.memory_provider import MemoryProviderError


def _require_non_empty_str(value, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MemoryProviderError(
            code="invalid_input",
            message=f"'{name}' must be a non-empty string",
        )


def _require_scope(scope) -> None:
    if not isinstance(scope, dict):
        raise MemoryProviderError(
            code="invalid_scope",
            message="'scope' must be a dict",
        )
    kind = scope.get("kind")
    if kind is not None and kind not in ("project", "ticket"):
        raise MemoryProviderError(
            code="invalid_scope",
            message=f"'scope.kind' must be 'project' or 'ticket', got '{kind}'",
        )


def save(content: str, scope: dict, metadata: dict | None = None) -> dict:
    """Validate and persist a memory.

    Returns
        {memory_id, content, scope, metadata, created_at}

    Raises
        MemoryProviderError — passed through from the provider.
    """
    _require_non_empty_str(content, "content")
    _require_scope(scope)
    return mempalace_adapter.get_provider().save(content, scope, metadata or {})


def retrieve(query: str, scope_filter: list[dict] | None = None, limit: int = 10) -> list[dict]:
    """Validate and perform a semantic search.

    Returns
        List of {memory_id, content, scope, metadata, score, created_at}

    Raises
        MemoryProviderError — passed through from the provider.
    """
    _require_non_empty_str(query, "query")
    if not isinstance(limit, int) or limit < 1:
        raise MemoryProviderError(
            code="invalid_input",
            message="'limit' must be a positive integer",
        )
    return mempalace_adapter.get_provider().retrieve(query, scope_filter, limit)


def get(memory_id: str) -> dict:
    """Fetch a single memory by ID.

    Returns
        {memory_id, content, scope, metadata, created_at}

    Raises
        MemoryProviderError — passed through from the provider.
    """
    _require_non_empty_str(memory_id, "memory_id")
    return mempalace_adapter.get_provider().get(memory_id)


def delete(memory_id: str) -> bool:
    """Remove a memory by ID.

    Returns
        True on success.

    Raises
        MemoryProviderError — passed through from the provider.
    """
    _require_non_empty_str(memory_id, "memory_id")
    return mempalace_adapter.get_provider().delete(memory_id)


def list_memories(scope_filter: list[dict] | None = None) -> list[dict]:
    """List stored memories, optionally filtered by scope.

    Returns
        List of {memory_id, content, scope, metadata, created_at}

    Raises
        MemoryProviderError — passed through from the provider.
    """
    return mempalace_adapter.get_provider().list_memories(scope_filter)
