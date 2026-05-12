"""Tests for memory MCP tools: memory_save, memory_retrieve, memory_get, memory_delete, memory_list."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.memory_provider import MemoryProviderError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_error_envelope(result: dict, expected_category: str, expected_retryable: bool) -> None:
    assert "error" in result and result["error"]
    assert result.get("errorCategory") == expected_category, (
        f"expected category={expected_category!r}, got {result.get('errorCategory')!r}"
    )
    assert result.get("isRetryable") == expected_retryable, (
        f"expected isRetryable={expected_retryable}, got {result.get('isRetryable')!r}"
    )


_SAVED_MEMORY = {
    "memory_id": "mem-1",
    "content": "some memory",
    "scope": {"kind": "project", "project_id": "p1"},
    "metadata": {},
    "created_at": "2024-01-01T00:00:00",
}

_RETRIEVED_MEMORY = {**_SAVED_MEMORY, "score": 0.9}


# ---------------------------------------------------------------------------
# memory_save
# ---------------------------------------------------------------------------

class TestMemorySaveMcpEnvelopes:
    def test_memory_save_provider_unavailable_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_save

        with patch(
            "mcp_tools.memory.memory_service.save",
            side_effect=MemoryProviderError(
                code="provider_unavailable",
                message="mempalace not installed; enable the mempalace module via Setup",
            ),
        ):
            result = memory_save(content="hello", scope={"kind": "project"})

        _assert_error_envelope(result, expected_category="business", expected_retryable=False)
        assert "hint" in result

    def test_memory_save_invalid_scope_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_save

        with patch(
            "mcp_tools.memory.memory_service.save",
            side_effect=MemoryProviderError(code="invalid_scope", message="scope malformed"),
        ):
            result = memory_save(content="hello", scope={})

        _assert_error_envelope(result, expected_category="validation", expected_retryable=False)

    def test_memory_save_transient_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_save

        with patch(
            "mcp_tools.memory.memory_service.save",
            side_effect=MemoryProviderError(code="transient", message="db timeout"),
        ):
            result = memory_save(content="hello", scope={"kind": "project"})

        _assert_error_envelope(result, expected_category="transient", expected_retryable=True)

    def test_memory_save_returns_saved_dict_on_success(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_save

        with patch("mcp_tools.memory.memory_service.save", return_value=_SAVED_MEMORY):
            result = memory_save(content="some memory", scope={"kind": "project", "project_id": "p1"})

        assert result["memory_id"] == "mem-1"
        assert result["content"] == "some memory"
        assert "error" not in result


# ---------------------------------------------------------------------------
# memory_retrieve
# ---------------------------------------------------------------------------

class TestMemoryRetrieveMcpEnvelopes:
    def test_memory_retrieve_with_scope_filter(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_retrieve

        with patch(
            "mcp_tools.memory.memory_service.retrieve",
            return_value=[_RETRIEVED_MEMORY],
        ):
            result = memory_retrieve(
                query="find notes",
                scope_filter=[{"kind": "project", "project_id": "p1"}],
                limit=5,
            )

        assert isinstance(result, list)
        assert result[0]["memory_id"] == "mem-1"
        assert result[0]["score"] == 0.9

    def test_memory_retrieve_provider_unavailable_returns_error_list(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_retrieve

        with patch(
            "mcp_tools.memory.memory_service.retrieve",
            side_effect=MemoryProviderError(
                code="provider_unavailable",
                message="not installed",
            ),
        ):
            result = memory_retrieve(query="find notes")

        assert isinstance(result, list)
        assert len(result) == 1
        _assert_error_envelope(result[0], expected_category="business", expected_retryable=False)

    def test_memory_retrieve_invalid_scope_returns_error_list(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_retrieve

        with patch(
            "mcp_tools.memory.memory_service.retrieve",
            side_effect=MemoryProviderError(code="invalid_scope", message="bad query"),
        ):
            result = memory_retrieve(query="find notes")

        assert isinstance(result, list)
        _assert_error_envelope(result[0], expected_category="validation", expected_retryable=False)


# ---------------------------------------------------------------------------
# memory_get
# ---------------------------------------------------------------------------

class TestMemoryGetMcpEnvelopes:
    def test_memory_get_not_found_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_get

        with patch(
            "mcp_tools.memory.memory_service.get",
            side_effect=MemoryProviderError(code="memory_not_found", message="id not found"),
        ):
            result = memory_get(memory_id="nonexistent")

        _assert_error_envelope(result, expected_category="not_found", expected_retryable=False)

    def test_memory_get_returns_dict_on_success(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_get

        with patch("mcp_tools.memory.memory_service.get", return_value=_SAVED_MEMORY):
            result = memory_get(memory_id="mem-1")

        assert result["memory_id"] == "mem-1"
        assert "error" not in result

    def test_memory_get_provider_unavailable_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_get

        with patch(
            "mcp_tools.memory.memory_service.get",
            side_effect=MemoryProviderError(code="provider_unavailable", message="not installed"),
        ):
            result = memory_get(memory_id="mem-1")

        _assert_error_envelope(result, expected_category="business", expected_retryable=False)


# ---------------------------------------------------------------------------
# memory_delete
# ---------------------------------------------------------------------------

class TestMemoryDeleteMcpEnvelopes:
    def test_memory_delete_returns_true_on_success(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_delete

        with patch("mcp_tools.memory.memory_service.delete", return_value=True):
            result = memory_delete(memory_id="mem-1")

        assert result == {"ok": True, "deleted_id": "mem-1"}

    def test_memory_delete_not_found_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_delete

        with patch(
            "mcp_tools.memory.memory_service.delete",
            side_effect=MemoryProviderError(code="memory_not_found", message="no such id"),
        ):
            result = memory_delete(memory_id="nonexistent")

        _assert_error_envelope(result, expected_category="not_found", expected_retryable=False)

    def test_memory_delete_provider_unavailable_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_delete

        with patch(
            "mcp_tools.memory.memory_service.delete",
            side_effect=MemoryProviderError(code="provider_unavailable", message="not installed"),
        ):
            result = memory_delete(memory_id="mem-1")

        _assert_error_envelope(result, expected_category="business", expected_retryable=False)


# ---------------------------------------------------------------------------
# memory_list
# ---------------------------------------------------------------------------

class TestMemoryListMcpEnvelopes:
    def test_memory_list_returns_list(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_list

        with patch(
            "mcp_tools.memory.memory_service.list_memories",
            return_value=[_SAVED_MEMORY],
        ):
            result = memory_list()

        assert isinstance(result, list)
        assert result[0]["memory_id"] == "mem-1"

    def test_memory_list_empty_when_no_memories(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_list

        with patch("mcp_tools.memory.memory_service.list_memories", return_value=[]):
            result = memory_list()

        assert result == []

    def test_memory_list_provider_unavailable_returns_error_list(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory import memory_list

        with patch(
            "mcp_tools.memory.memory_service.list_memories",
            side_effect=MemoryProviderError(code="provider_unavailable", message="not installed"),
        ):
            result = memory_list()

        assert isinstance(result, list)
        assert len(result) == 1
        _assert_error_envelope(result[0], expected_category="business", expected_retryable=False)
