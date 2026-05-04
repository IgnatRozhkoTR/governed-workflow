"""MemPalace adapter for the MemoryProvider interface.

Bypasses MemPalace's MCP transport (broken per upstream issue #538) and calls
the Python library directly.

MemPalace v3.3.4 API surface used:
    palace = MemPalace(palace_dir)
    palace.add_drawer(wing, room, content, metadata) -> {"id": str, ...}
    palace.search(query, wing=None, room=None, limit=10) -> [{"id": str, ...}, ...]
    palace.get_drawer(drawer_id) -> {"id": str, ...}
    palace.delete_drawer(drawer_id) -> bool
    palace.list_drawers(wing=None, room=None) -> [{"id": str, ...}, ...]

Scope → MemPalace mapping:
    wing  = scope.get("kind", "project")
    room  = slash-joined remaining scope fields (project_id, workspace_id, etc.)
"""
import os
from pathlib import Path

from core.paths import REPO_ROOT
from services.memory_provider import MemoryProvider, MemoryProviderError


def _default_palace_dir() -> Path:
    env = os.environ.get("GW_MEMPALACE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT / ".local" / "mempalace"


_singleton: MemoryProvider | None = None


def _encode_room(scope: dict) -> str:
    """Build a room path from scope fields excluding 'kind'."""
    parts = []
    for key in ("project_id", "workspace_id"):
        value = scope.get(key)
        if value is not None:
            parts.append(str(value))
    extras = sorted(k for k in scope if k not in ("kind", "project_id", "workspace_id"))
    for key in extras:
        parts.append(f"{key}={scope[key]}")
    return "/".join(parts) if parts else "default"


def _drawer_to_dict(drawer: dict) -> dict:
    return {
        "memory_id": drawer.get("id") or drawer.get("drawer_id") or "",
        "content": drawer.get("content", ""),
        "scope": drawer.get("metadata", {}).get("_scope", {}),
        "metadata": {k: v for k, v in drawer.get("metadata", {}).items() if k != "_scope"},
        "created_at": drawer.get("created_at", ""),
    }


def _search_result_to_dict(item: dict) -> dict:
    base = _drawer_to_dict(item)
    base["score"] = item.get("score", 0.0)
    return base


class MemPalaceAdapter(MemoryProvider):
    """Concrete MemoryProvider backed by the mempalace Python library."""

    def __init__(self, palace_dir: Path):
        try:
            import mempalace  # noqa: PLC0415
            self._mempalace = mempalace
        except ImportError as exc:
            raise MemoryProviderError(
                code="provider_unavailable",
                message="mempalace not installed; enable the mempalace module via Setup",
            ) from exc
        palace_dir.mkdir(parents=True, exist_ok=True)
        self._palace = self._mempalace.MemPalace(str(palace_dir))

    def save(self, content: str, scope: dict, metadata: dict) -> dict:
        wing = scope.get("kind", "project")
        room = _encode_room(scope)
        combined_metadata = dict(metadata)
        combined_metadata["_scope"] = scope
        try:
            drawer = self._palace.add_drawer(wing, room, content, combined_metadata)
        except self._mempalace.PalaceNotFoundError as exc:
            raise MemoryProviderError(code="invalid_scope", message=str(exc)) from exc
        except self._mempalace.PalaceError as exc:
            raise MemoryProviderError(code="transient", message=str(exc)) from exc
        return _drawer_to_dict(drawer)

    def retrieve(self, query: str, scope_filter: list[dict] | None, limit: int = 10) -> list[dict]:
        wing = None
        room = None
        if scope_filter:
            first = scope_filter[0]
            wing = first.get("kind")
            room = _encode_room(first) if len(first) > 1 else None
        try:
            results = self._palace.search(query, wing=wing, room=room, limit=limit)
        except self._mempalace.PalaceError as exc:
            raise MemoryProviderError(code="transient", message=str(exc)) from exc
        return [_search_result_to_dict(item) for item in results]

    def get(self, memory_id: str) -> dict:
        try:
            drawer = self._palace.get_drawer(memory_id)
        except self._mempalace.DrawerNotFoundError as exc:
            raise MemoryProviderError(code="memory_not_found", message=str(exc)) from exc
        except self._mempalace.PalaceError as exc:
            raise MemoryProviderError(code="transient", message=str(exc)) from exc
        return _drawer_to_dict(drawer)

    def delete(self, memory_id: str) -> bool:
        try:
            return bool(self._palace.delete_drawer(memory_id))
        except self._mempalace.DrawerNotFoundError as exc:
            raise MemoryProviderError(code="memory_not_found", message=str(exc)) from exc
        except self._mempalace.PalaceError as exc:
            raise MemoryProviderError(code="transient", message=str(exc)) from exc

    def list_memories(self, scope_filter: list[dict] | None) -> list[dict]:
        wing = None
        room = None
        if scope_filter:
            first = scope_filter[0]
            wing = first.get("kind")
            room = _encode_room(first) if len(first) > 1 else None
        try:
            drawers = self._palace.list_drawers(wing=wing, room=room)
        except self._mempalace.PalaceError as exc:
            raise MemoryProviderError(code="transient", message=str(exc)) from exc
        return [_drawer_to_dict(d) for d in drawers]


def get_provider(palace_dir: Path | None = None) -> MemoryProvider:
    """Return the singleton MemPalaceAdapter, initialising it on first call.

    ``palace_dir`` overrides the default directory resolved by
    ``_default_palace_dir()`` (which honours ``GW_MEMPALACE_DIR``). Passing a
    value is useful in tests to scope storage to a ``tmp_path`` without
    touching the global env.

    Raises MemoryProviderError(code='provider_unavailable') when mempalace is
    not installed. Callers should treat this as a configuration error and surface
    the hint to the user.
    """
    global _singleton
    if _singleton is None:
        resolved_dir = palace_dir if palace_dir is not None else _default_palace_dir()
        _singleton = MemPalaceAdapter(resolved_dir)
    return _singleton
