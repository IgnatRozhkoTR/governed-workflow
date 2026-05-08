"""Tests for memory_service: input validation and delegation to provider."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.memory_provider import MemoryProviderError, register_provider, _clear_registry


# ---------------------------------------------------------------------------
# Fake provider + DB helpers
# ---------------------------------------------------------------------------

def _fake_provider():
    provider = MagicMock()
    _store = {}

    def _save(content, scope, metadata):
        mid = f"mem-{len(_store) + 1}"
        record = {
            "memory_id": mid,
            "content": content,
            "scope": scope,
            "metadata": metadata,
            "created_at": "2024-01-01T00:00:00",
        }
        _store[mid] = record
        return record

    def _get(memory_id):
        if memory_id not in _store:
            raise MemoryProviderError(code="memory_not_found", message=f"{memory_id} not found")
        return _store[memory_id]

    def _delete(memory_id):
        if memory_id not in _store:
            raise MemoryProviderError(code="memory_not_found", message=f"{memory_id} not found")
        del _store[memory_id]
        return True

    def _retrieve(query, scope_filter, limit=10):
        return []

    def _list(scope_filter):
        return list(_store.values())

    provider.save.side_effect = _save
    provider.get.side_effect = _get
    provider.delete.side_effect = _delete
    provider.retrieve.side_effect = _retrieve
    provider.list_memories.side_effect = _list
    return provider


def _mock_db_with_module(module_id: str):
    """Return a minimal mock DB whose modules_enabled query returns module_id."""
    db = MagicMock()
    row = MagicMock()
    row.__getitem__ = lambda self, key: module_id if key == "module_id" else None
    db.execute.return_value.fetchall.return_value = [row]
    return db


@pytest.fixture(autouse=True)
def clean_registry():
    """Restore the registry to its pre-test state after each test."""
    import services.mempalace_adapter  # ensure "mempalace" is registered
    from services.memory_provider import _REGISTRY
    snapshot = dict(_REGISTRY)
    yield
    _clear_registry()
    _REGISTRY.update(snapshot)


# ---------------------------------------------------------------------------
# Validation tests: save()
# ---------------------------------------------------------------------------

class TestMemoryServiceSaveValidation:
    def test_save_validates_content_non_empty(self):
        from services import memory_service

        db = MagicMock()
        with pytest.raises(MemoryProviderError) as exc_info:
            memory_service.save(db, "", scope={"kind": "project"})

        assert exc_info.value.code == "invalid_input"
        assert "content" in str(exc_info.value)

    def test_save_validates_content_whitespace_only(self):
        from services import memory_service

        db = MagicMock()
        with pytest.raises(MemoryProviderError) as exc_info:
            memory_service.save(db, "   ", scope={"kind": "project"})

        assert exc_info.value.code == "invalid_input"

    def test_save_validates_scope_is_dict(self):
        from services import memory_service

        db = MagicMock()
        with pytest.raises(MemoryProviderError) as exc_info:
            memory_service.save(db, "valid content", scope="project")

        assert exc_info.value.code == "invalid_scope"
        assert "scope" in str(exc_info.value)

    def test_save_validates_scope_kind_must_be_project_or_ticket(self):
        from services import memory_service

        db = MagicMock()
        with pytest.raises(MemoryProviderError) as exc_info:
            memory_service.save(db, "valid content", scope={"kind": "global"})

        assert exc_info.value.code == "invalid_scope"

    def test_save_accepts_scope_without_kind(self):
        provider = _fake_provider()
        register_provider("test-fake", lambda: provider)
        db = _mock_db_with_module("test-fake")

        from services import memory_service
        result = memory_service.save(db, "content", scope={"project_id": "p1"})

        assert result["memory_id"] == "mem-1"

    def test_save_accepts_scope_kind_project(self):
        provider = _fake_provider()
        register_provider("test-fake", lambda: provider)
        db = _mock_db_with_module("test-fake")

        from services import memory_service
        result = memory_service.save(db, "content", scope={"kind": "project", "project_id": "p1"})

        assert result["memory_id"] is not None

    def test_save_accepts_scope_kind_ticket(self):
        provider = _fake_provider()
        register_provider("test-fake", lambda: provider)
        db = _mock_db_with_module("test-fake")

        from services import memory_service
        result = memory_service.save(db, "content", scope={"kind": "ticket"})

        assert result["memory_id"] is not None


# ---------------------------------------------------------------------------
# Validation tests: retrieve()
# ---------------------------------------------------------------------------

class TestMemoryServiceRetrieveValidation:
    def test_retrieve_validates_query_non_empty(self):
        from services import memory_service

        db = MagicMock()
        with pytest.raises(MemoryProviderError) as exc_info:
            memory_service.retrieve(db, "")

        assert exc_info.value.code == "invalid_input"
        assert "query" in str(exc_info.value)

    def test_retrieve_validates_limit_in_range(self):
        from services import memory_service

        db = MagicMock()
        with pytest.raises(MemoryProviderError) as exc_info:
            memory_service.retrieve(db, "q", limit=0)

        assert exc_info.value.code == "invalid_input"
        assert "limit" in str(exc_info.value)

    def test_retrieve_validates_limit_negative(self):
        from services import memory_service

        db = MagicMock()
        with pytest.raises(MemoryProviderError) as exc_info:
            memory_service.retrieve(db, "q", limit=-5)

        assert exc_info.value.code == "invalid_input"

    def test_retrieve_delegates_to_provider_on_valid_input(self):
        provider = _fake_provider()
        register_provider("test-fake", lambda: provider)
        db = _mock_db_with_module("test-fake")

        from services import memory_service
        results = memory_service.retrieve(db, "find stuff", limit=3)

        provider.retrieve.assert_called_once_with("find stuff", None, 3)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Happy-path round-trip
# ---------------------------------------------------------------------------

class TestMemoryServiceRoundTrip:
    def test_save_get_delete_round_trip(self):
        provider = _fake_provider()
        register_provider("test-fake", lambda: provider)
        db = _mock_db_with_module("test-fake")

        from services import memory_service

        scope = {"kind": "project", "project_id": "proj-42"}
        saved = memory_service.save(db, "important note", scope=scope, metadata={"author": "me"})

        assert saved["memory_id"] is not None
        assert saved["content"] == "important note"
        assert saved["scope"] == scope

        fetched = memory_service.get(db, saved["memory_id"])
        assert fetched["memory_id"] == saved["memory_id"]
        assert fetched["content"] == "important note"

        deleted = memory_service.delete(db, saved["memory_id"])
        assert deleted is True

        with pytest.raises(MemoryProviderError) as exc_info:
            memory_service.get(db, saved["memory_id"])
        assert exc_info.value.code == "memory_not_found"

    def test_list_returns_saved_memories(self):
        provider = _fake_provider()
        register_provider("test-fake", lambda: provider)
        db = _mock_db_with_module("test-fake")

        from services import memory_service

        memory_service.save(db, "note A", scope={"kind": "project"})
        memory_service.save(db, "note B", scope={"kind": "ticket"})

        items = memory_service.list_memories(db)

        assert len(items) == 2
