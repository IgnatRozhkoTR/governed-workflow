"""Tests for reflection MCP tools: reflection_run, reflection_get, reflection_list."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.reflection_service import ReflectionServiceError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(db) -> dict:
    db.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        ("test-project", "Test Project", "/tmp/test", "2024-01-01"),
    )
    cursor = db.execute(
        "INSERT INTO workspaces "
        "(project_id, branch, sanitized_branch, working_dir, created, status, phase, scope_json, plan_json, source_branch) "
        "VALUES ('test-project', 'feature/x', 'feature-x', '/tmp/test', '2024-01-01', 'active', '0', '{}', '{}', 'main')"
    )
    ws_id = cursor.lastrowid
    db.commit()
    return ws_id


def _assert_error_envelope(result: dict, expected_category: str, expected_retryable: bool) -> None:
    assert "error" in result and result["error"]
    assert result.get("errorCategory") == expected_category, (
        f"expected category={expected_category!r}, got {result.get('errorCategory')!r}"
    )
    assert result.get("isRetryable") == expected_retryable, (
        f"expected isRetryable={expected_retryable}, got {result.get('isRetryable')!r}"
    )


# ---------------------------------------------------------------------------
# reflection_run MCP tool error envelope tests
# ---------------------------------------------------------------------------

class TestReflectionRunMcpEnvelopes:
    def test_reflection_run_mcp_envelope_on_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.reflection import reflection_run

        with patch(
            "mcp_tools.reflection.reflection_service.run",
            side_effect=ReflectionServiceError("workspace missing", code="not_found"),
        ):
            result = reflection_run()

        _assert_error_envelope(result, expected_category="not_found", expected_retryable=False)

    def test_reflection_run_mcp_envelope_on_llm_unconfigured(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.reflection import reflection_run

        with patch(
            "mcp_tools.reflection.reflection_service.run",
            side_effect=ReflectionServiceError("no API key", code="llm_unconfigured"),
        ):
            result = reflection_run()

        _assert_error_envelope(result, expected_category="business", expected_retryable=False)

    def test_reflection_run_mcp_envelope_on_no_session_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.reflection import reflection_run

        with patch(
            "mcp_tools.reflection.reflection_service.run",
            side_effect=ReflectionServiceError("no JSONL", code="no_session_found"),
        ):
            result = reflection_run()

        _assert_error_envelope(result, expected_category="transient", expected_retryable=True)

    def test_reflection_run_mcp_envelope_on_llm_failure(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.reflection import reflection_run

        with patch(
            "mcp_tools.reflection.reflection_service.run",
            side_effect=ReflectionServiceError("connection reset", code="llm_failure"),
        ):
            result = reflection_run()

        _assert_error_envelope(result, expected_category="transient", expected_retryable=True)


# ---------------------------------------------------------------------------
# reflection_get MCP tool error envelope tests
# ---------------------------------------------------------------------------

class TestReflectionGetMcpEnvelopes:
    def test_reflection_get_mcp_envelope_on_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.reflection import reflection_get

        with patch(
            "mcp_tools.reflection.reflection_service.get",
            side_effect=ReflectionServiceError("reflection missing", code="not_found"),
        ):
            result = reflection_get(reflection_id=99999)

        _assert_error_envelope(result, expected_category="not_found", expected_retryable=False)


# ---------------------------------------------------------------------------
# reflection_list MCP tool error envelope tests
# ---------------------------------------------------------------------------

class TestReflectionListMcpEnvelopes:
    def test_reflection_list_mcp_envelope_on_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.reflection import reflection_list

        with patch(
            "mcp_tools.reflection.reflection_service.list_reflections",
            side_effect=ReflectionServiceError("workspace missing", code="not_found"),
        ):
            result = reflection_list()

        assert isinstance(result, list)
        assert len(result) == 1
        _assert_error_envelope(result[0], expected_category="not_found", expected_retryable=False)
