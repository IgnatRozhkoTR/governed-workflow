"""Tests for MemPalaceAdapter — mempalace module stubbed via sys.modules."""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.memory_provider import MemoryProviderError


# ---------------------------------------------------------------------------
# Stub mempalace module
# ---------------------------------------------------------------------------

def _make_stub_mempalace():
    """Build a fake mempalace module with the API surface the adapter needs."""

    class DrawerNotFoundError(Exception):
        pass

    class PalaceNotFoundError(Exception):
        pass

    class PalaceError(Exception):
        pass

    class FakePalace:
        def __init__(self, palace_dir: str):
            self._dir = palace_dir

        def add_drawer(self, wing, room, content, metadata):
            return {
                "id": "drawer-1",
                "content": content,
                "metadata": metadata,
                "created_at": "2024-01-01T00:00:00",
            }

        def search(self, query, wing=None, room=None, limit=10):
            return [
                {
                    "id": "drawer-1",
                    "content": "found content",
                    "metadata": {"_scope": {"kind": "project"}},
                    "created_at": "2024-01-01T00:00:00",
                    "score": 0.9,
                }
            ]

        def get_drawer(self, drawer_id):
            return {
                "id": drawer_id,
                "content": "stored content",
                "metadata": {"_scope": {"kind": "project"}, "tag": "x"},
                "created_at": "2024-01-01T00:00:00",
            }

        def delete_drawer(self, drawer_id):
            return True

        def list_drawers(self, wing=None, room=None):
            return [
                {
                    "id": "drawer-1",
                    "content": "content",
                    "metadata": {"_scope": {"kind": "project"}},
                    "created_at": "2024-01-01T00:00:00",
                }
            ]

    stub = types.ModuleType("mempalace")
    stub.MemPalace = FakePalace
    stub.DrawerNotFoundError = DrawerNotFoundError
    stub.PalaceNotFoundError = PalaceNotFoundError
    stub.PalaceError = PalaceError
    return stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the adapter singleton before each test."""
    import services.mempalace_adapter as mod
    original = mod._singleton
    mod._singleton = None
    yield
    mod._singleton = original


@pytest.fixture
def stub_mempalace(monkeypatch):
    stub = _make_stub_mempalace()
    monkeypatch.setitem(sys.modules, "mempalace", stub)
    return stub


@pytest.fixture
def adapter(stub_mempalace, tmp_path):
    from services.mempalace_adapter import MemPalaceAdapter
    return MemPalaceAdapter(tmp_path / "palace")


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestMemPalaceAdapterSave:
    def test_save_returns_id_and_maps_scope_to_wing_room(self, adapter):
        scope = {"kind": "project", "project_id": "proj-1"}

        result = adapter.save("remember this", scope, {"tag": "v1"})

        assert result["memory_id"] == "drawer-1"
        assert result["content"] == "remember this"
        assert result["scope"] == scope
        assert "metadata" in result
        assert "created_at" in result

    def test_save_uses_kind_as_wing(self, stub_mempalace, tmp_path):
        calls = []
        original = stub_mempalace.MemPalace

        class RecordingPalace(original):
            def add_drawer(self, wing, room, content, metadata):
                calls.append((wing, room))
                return super().add_drawer(wing, room, content, metadata)

        stub_mempalace.MemPalace = RecordingPalace
        from services.mempalace_adapter import MemPalaceAdapter

        a = MemPalaceAdapter(tmp_path / "palace2")
        a.save("content", {"kind": "ticket", "project_id": "p-1"}, {})

        assert calls[0][0] == "ticket"

    def test_save_encodes_room_from_project_id_and_workspace_id(self, stub_mempalace, tmp_path):
        calls = []
        original = stub_mempalace.MemPalace

        class RecordingPalace(original):
            def add_drawer(self, wing, room, content, metadata):
                calls.append((wing, room))
                return super().add_drawer(wing, room, content, metadata)

        stub_mempalace.MemPalace = RecordingPalace
        from services.mempalace_adapter import MemPalaceAdapter

        a = MemPalaceAdapter(tmp_path / "palace3")
        a.save("c", {"kind": "project", "project_id": "my-proj", "workspace_id": 7}, {})

        assert calls[0][1] == "my-proj/7"

    def test_save_uses_default_room_when_scope_has_only_kind(self, stub_mempalace, tmp_path):
        calls = []
        original = stub_mempalace.MemPalace

        class RecordingPalace(original):
            def add_drawer(self, wing, room, content, metadata):
                calls.append((wing, room))
                return super().add_drawer(wing, room, content, metadata)

        stub_mempalace.MemPalace = RecordingPalace
        from services.mempalace_adapter import MemPalaceAdapter

        a = MemPalaceAdapter(tmp_path / "palace4")
        a.save("c", {"kind": "project"}, {})

        assert calls[0][1] == "default"


class TestMemPalaceAdapterRetrieve:
    def test_retrieve_passes_scope_filter_through(self, stub_mempalace, tmp_path):
        calls = []
        original = stub_mempalace.MemPalace

        class RecordingPalace(original):
            def search(self, query, wing=None, room=None, limit=10):
                calls.append({"query": query, "wing": wing, "room": room, "limit": limit})
                return super().search(query, wing=wing, room=room, limit=limit)

        stub_mempalace.MemPalace = RecordingPalace
        from services.mempalace_adapter import MemPalaceAdapter

        a = MemPalaceAdapter(tmp_path / "palace5")
        scope_filter = [{"kind": "ticket", "project_id": "p-2"}]
        results = a.retrieve("find something", scope_filter, limit=5)

        assert calls[0]["query"] == "find something"
        assert calls[0]["wing"] == "ticket"
        assert calls[0]["limit"] == 5
        assert isinstance(results, list)
        assert "score" in results[0]

    def test_retrieve_with_no_scope_filter(self, adapter):
        results = adapter.retrieve("search query", scope_filter=None)

        assert isinstance(results, list)


class TestMemPalaceAdapterGet:
    def test_get_returns_drawer_dict(self, adapter):
        result = adapter.get("drawer-abc")

        assert result["memory_id"] == "drawer-abc"
        assert result["content"] == "stored content"
        assert result["scope"] == {"kind": "project"}
        assert result["metadata"] == {"tag": "x"}


class TestMemPalaceAdapterDelete:
    def test_delete_returns_true_on_success(self, adapter):
        result = adapter.delete("drawer-abc")

        assert result is True


class TestMemPalaceAdapterList:
    def test_list_returns_drawers(self, adapter):
        results = adapter.list_memories(scope_filter=None)

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["memory_id"] == "drawer-1"


# ---------------------------------------------------------------------------
# Error mapping tests
# ---------------------------------------------------------------------------

class TestMemPalaceAdapterErrorMapping:
    def test_import_error_raises_provider_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "mempalace", None)

        from services.mempalace_adapter import MemPalaceAdapter

        with pytest.raises(MemoryProviderError) as exc_info:
            MemPalaceAdapter(tmp_path / "palace-err")

        assert exc_info.value.code == "provider_unavailable"
        assert "mempalace" in str(exc_info.value).lower()

    def test_drawer_not_found_maps_to_memory_not_found_error(self, stub_mempalace, tmp_path):
        original = stub_mempalace.MemPalace
        DrawerNotFoundError = stub_mempalace.DrawerNotFoundError

        class FailingPalace(original):
            def get_drawer(self, drawer_id):
                raise DrawerNotFoundError("no such drawer")

            def delete_drawer(self, drawer_id):
                raise DrawerNotFoundError("no such drawer")

        stub_mempalace.MemPalace = FailingPalace
        from services.mempalace_adapter import MemPalaceAdapter

        a = MemPalaceAdapter(tmp_path / "palace-nf")

        with pytest.raises(MemoryProviderError) as exc_info:
            a.get("missing-id")
        assert exc_info.value.code == "memory_not_found"

        with pytest.raises(MemoryProviderError) as exc_info:
            a.delete("missing-id")
        assert exc_info.value.code == "memory_not_found"

    def test_palace_not_found_in_save_maps_to_invalid_scope(self, stub_mempalace, tmp_path):
        original = stub_mempalace.MemPalace
        PalaceNotFoundError = stub_mempalace.PalaceNotFoundError

        class FailingPalace(original):
            def add_drawer(self, wing, room, content, metadata):
                raise PalaceNotFoundError("palace missing")

        stub_mempalace.MemPalace = FailingPalace
        from services.mempalace_adapter import MemPalaceAdapter

        a = MemPalaceAdapter(tmp_path / "palace-inv")

        with pytest.raises(MemoryProviderError) as exc_info:
            a.save("c", {"kind": "project"}, {})
        assert exc_info.value.code == "invalid_scope"

    def test_unexpected_exception_maps_to_transient(self, stub_mempalace, tmp_path):
        original = stub_mempalace.MemPalace

        class FailingPalace(original):
            def search(self, query, wing=None, room=None, limit=10):
                raise RuntimeError("unexpected boom")

            def list_drawers(self, wing=None, room=None):
                raise RuntimeError("unexpected boom")

        stub_mempalace.MemPalace = FailingPalace
        from services.mempalace_adapter import MemPalaceAdapter

        a = MemPalaceAdapter(tmp_path / "palace-tx")

        with pytest.raises(MemoryProviderError) as exc_info:
            a.retrieve("query", scope_filter=None)
        assert exc_info.value.code == "transient"

        with pytest.raises(MemoryProviderError) as exc_info:
            a.list_memories(scope_filter=None)
        assert exc_info.value.code == "transient"


# ---------------------------------------------------------------------------
# get_provider singleton tests
# ---------------------------------------------------------------------------

class TestGetProvider:
    def test_get_provider_raises_provider_unavailable_when_mempalace_missing(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setitem(sys.modules, "mempalace", None)

        from services import mempalace_adapter

        with pytest.raises(MemoryProviderError) as exc_info:
            mempalace_adapter.get_provider()

        assert exc_info.value.code == "provider_unavailable"

    def test_get_provider_returns_singleton(self, stub_mempalace, tmp_path, monkeypatch):
        import services.mempalace_adapter as mod
        monkeypatch.setattr(mod, "_PALACE_DIR", tmp_path / "singleton-palace")

        from services import mempalace_adapter

        p1 = mempalace_adapter.get_provider()
        p2 = mempalace_adapter.get_provider()

        assert p1 is p2
