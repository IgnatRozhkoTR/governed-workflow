"""Thin validation wrapper over the memory provider.

Validates inputs before delegating to the provider resolved from the
active modules_enabled configuration. MemoryProviderError codes pass through
unchanged so callers (routes, MCP tools) can map them consistently.
"""
import services.mempalace_adapter  # noqa: F401 — side-effect: registers "mempalace" provider
from services.memory_provider import MemoryProviderError, get_active_provider


def _provider(db):
    """Resolve the active memory provider from the modules_enabled table."""
    rows = db.execute("SELECT module_id FROM modules_enabled").fetchall()
    enabled_ids = [row["module_id"] for row in rows]
    return get_active_provider(enabled_ids)


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


def save(db, content: str, scope: dict, metadata: dict | None = None) -> dict:
    """Validate and persist a memory.

    Returns
        {memory_id, content, scope, metadata, created_at}

    Raises
        MemoryProviderError — passed through from the provider.
    """
    _require_non_empty_str(content, "content")
    _require_scope(scope)
    return _provider(db).save(content, scope, metadata or {})


def retrieve(db, query: str, scope_filter: list[dict] | None = None, limit: int = 10) -> list[dict]:
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
    return _provider(db).retrieve(query, scope_filter, limit)


def get(db, memory_id: str) -> dict:
    """Fetch a single memory by ID.

    Returns
        {memory_id, content, scope, metadata, created_at}

    Raises
        MemoryProviderError — passed through from the provider.
    """
    _require_non_empty_str(memory_id, "memory_id")
    return _provider(db).get(memory_id)


def delete(db, memory_id: str) -> bool:
    """Remove a memory by ID.

    Returns
        True on success.

    Raises
        MemoryProviderError — passed through from the provider.
    """
    _require_non_empty_str(memory_id, "memory_id")
    return _provider(db).delete(memory_id)


def list_memories(db, scope_filter: list[dict] | None = None) -> list[dict]:
    """List stored memories, optionally filtered by scope.

    Returns
        List of {memory_id, content, scope, metadata, created_at}

    Raises
        MemoryProviderError — passed through from the provider.
    """
    return _provider(db).list_memories(scope_filter)
