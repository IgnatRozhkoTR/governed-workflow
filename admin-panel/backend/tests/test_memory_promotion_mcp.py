"""Tests for memory_promotion MCP tool: memory_promotion_run."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.memory_promotion_service import MemoryPromotionError


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


# ---------------------------------------------------------------------------
# memory_promotion_run MCP tool tests
# ---------------------------------------------------------------------------

class TestMemoryPromotionRunMcp:
    def test_memory_promotion_run_happy_path(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory_promotion import memory_promotion_run

        expected = {
            "workspace_id": workspace["id"],
            "candidates_examined": 3,
            "proposals_created": 2,
            "proposal_ids": [10, 11],
        }
        with patch(
            "mcp_tools.memory_promotion.memory_promotion_service.promote",
            return_value=expected,
        ):
            result = memory_promotion_run()

        assert result["workspace_id"] == workspace["id"]
        assert result["candidates_examined"] == 3
        assert result["proposals_created"] == 2
        assert result["proposal_ids"] == [10, 11]

    def test_memory_promotion_run_not_found_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory_promotion import memory_promotion_run

        with patch(
            "mcp_tools.memory_promotion.memory_promotion_service.promote",
            side_effect=MemoryPromotionError("Workspace 99 not found", code="not_found"),
        ):
            result = memory_promotion_run()

        _assert_error_envelope(result, expected_category="not_found", expected_retryable=False)

    def test_memory_promotion_run_llm_unconfigured_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory_promotion import memory_promotion_run

        with patch(
            "mcp_tools.memory_promotion.memory_promotion_service.promote",
            side_effect=MemoryPromotionError("No LLM API key configured.", code="llm_unconfigured"),
        ):
            result = memory_promotion_run()

        _assert_error_envelope(result, expected_category="business", expected_retryable=False)
        assert "hint" in result
        assert "OPENAI_API_KEY" in result["hint"] or "ANTHROPIC_API_KEY" in result["hint"]

    def test_memory_promotion_run_provider_unavailable_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory_promotion import memory_promotion_run

        with patch(
            "mcp_tools.memory_promotion.memory_promotion_service.promote",
            side_effect=MemoryPromotionError("mempalace not installed", code="provider_unavailable"),
        ):
            result = memory_promotion_run()

        _assert_error_envelope(result, expected_category="business", expected_retryable=False)
        assert "hint" in result
        assert "mempalace" in result["hint"].lower()

    def test_memory_promotion_run_transient_envelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.memory_promotion import memory_promotion_run

        with patch(
            "mcp_tools.memory_promotion.memory_promotion_service.promote",
            side_effect=MemoryPromotionError("connection reset", code="transient"),
        ):
            result = memory_promotion_run()

        _assert_error_envelope(result, expected_category="transient", expected_retryable=True)
