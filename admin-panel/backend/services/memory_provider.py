"""Abstract base class for memory storage providers.

Scope canonical shape:
    {
        "kind": "project" | "ticket",
        "project_id": str,           # optional, used when kind="project"
        "workspace_id": int,         # optional
        # Additional free-form path elements are allowed and mapped to
        # MemPalace's wing/room/drawer hierarchy.
    }

Error codes:
    provider_unavailable — the backing library or service is not installed/reachable.
    memory_not_found     — the requested memory_id does not exist.
    invalid_scope        — the scope dict is malformed or missing required fields.
    transient            — temporary failure; caller may retry.
"""
from abc import ABC, abstractmethod


class MemoryProviderError(Exception):
    """Domain error for memory provider operations."""

    def __init__(self, code: str, message: str | None = None, details: dict | None = None):
        super().__init__(message or code)
        self.code = code
        self.details = details or {}


class MemoryProvider(ABC):
    """Interface for memory storage backends."""

    @abstractmethod
    def save(self, content: str, scope: dict, metadata: dict) -> dict:
        """Persist a memory and return its stored representation.

        Returns
            {memory_id, content, scope, metadata, created_at}

        Raises
            MemoryProviderError(code='provider_unavailable')
            MemoryProviderError(code='invalid_scope')
            MemoryProviderError(code='transient')
        """

    @abstractmethod
    def retrieve(self, query: str, scope_filter: list[dict] | None, limit: int = 10) -> list[dict]:
        """Semantic search over stored memories.

        Returns
            List of {memory_id, content, scope, metadata, score, created_at}

        Raises
            MemoryProviderError(code='provider_unavailable')
            MemoryProviderError(code='invalid_scope')
            MemoryProviderError(code='transient')
        """

    @abstractmethod
    def get(self, memory_id: str) -> dict:
        """Fetch a single memory by ID.

        Returns
            {memory_id, content, scope, metadata, created_at}

        Raises
            MemoryProviderError(code='memory_not_found')
            MemoryProviderError(code='provider_unavailable')
            MemoryProviderError(code='transient')
        """

    @abstractmethod
    def delete(self, memory_id: str) -> bool:
        """Remove a memory by ID. Returns True on success.

        Raises
            MemoryProviderError(code='memory_not_found')
            MemoryProviderError(code='provider_unavailable')
            MemoryProviderError(code='transient')
        """

    @abstractmethod
    def list_memories(self, scope_filter: list[dict] | None) -> list[dict]:
        """List all stored memories, optionally filtered by scope.

        Returns
            List of {memory_id, content, scope, metadata, created_at}

        Raises
            MemoryProviderError(code='provider_unavailable')
            MemoryProviderError(code='invalid_scope')
            MemoryProviderError(code='transient')
        """
