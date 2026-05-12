"""Tests for proposal MCP tools: error envelopes and happy paths."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.proposal_service import ProposalServiceError


def _assert_error_envelope(result: dict, expected_category: str, expected_retryable: bool) -> None:
    assert "error" in result and result["error"]
    assert result.get("errorCategory") == expected_category, (
        f"expected category={expected_category!r}, got {result.get('errorCategory')!r}"
    )
    assert result.get("isRetryable") == expected_retryable, (
        f"expected isRetryable={expected_retryable}, got {result.get('isRetryable')!r}"
    )


_PENDING_PROPOSAL = {
    "id": 1,
    "type": "memory_write",
    "status": "pending",
    "title": "Save a note",
    "body": "",
    "payload": {"content": "hello"},
    "origin": "agent",
    "workspace_id": None,
    "project_id": None,
    "created_at": "2024-01-01T00:00:00",
    "reviewed_at": None,
    "executed_at": None,
    "result": None,
    "reason": None,
}

_APPROVED_PROPOSAL = {**_PENDING_PROPOSAL, "status": "approved", "reviewed_at": "2024-01-01T01:00:00"}


class TestProposalCreateMcp:
    def test_proposalCreate_happyPath_returnsPendingProposal(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.proposals import proposal_create

        with patch("mcp_tools.proposals.proposal_service.create", return_value=_PENDING_PROPOSAL):
            result = proposal_create(
                type="memory_write",
                title="Save a note",
                payload={"content": "hello"},
            )

        assert result["status"] == "pending"
        assert result["type"] == "memory_write"
        assert result["id"] == 1

    def test_proposalCreate_invalidType_returnsValidationError(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.proposals import proposal_create

        result = proposal_create(
            type="not_a_real_type",
            title="Bad type",
        )

        _assert_error_envelope(result, expected_category="validation", expected_retryable=False)

    def test_proposalCreate_serviceError_returnsErrorEnvelope(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_tools.proposals import proposal_create

        with patch(
            "mcp_tools.proposals.proposal_service.create",
            side_effect=ProposalServiceError("title empty", code="invalid_payload"),
        ):
            result = proposal_create(type="memory_write", title="x")

        _assert_error_envelope(result, expected_category="validation", expected_retryable=False)


class TestProposalListMcp:
    def test_proposalList_happyPath_returnsList(self, clean_db):
        from mcp_tools.proposals import proposal_list

        with patch(
            "mcp_tools.proposals.proposal_service.list_proposals",
            return_value=[_PENDING_PROPOSAL],
        ):
            result = proposal_list()

        assert isinstance(result, list)
        assert result[0]["id"] == 1


class TestProposalGetMcp:
    def test_proposalGet_happyPath_returnsProposal(self, clean_db):
        from mcp_tools.proposals import proposal_get

        with patch("mcp_tools.proposals.proposal_service.get", return_value=_PENDING_PROPOSAL):
            result = proposal_get(proposal_id=1)

        assert result["id"] == 1
        assert "error" not in result

    def test_proposalGet_notFound_returnsNotFoundEnvelope(self, clean_db):
        from mcp_tools.proposals import proposal_get

        with patch(
            "mcp_tools.proposals.proposal_service.get",
            side_effect=ProposalServiceError("not found", code="not_found"),
        ):
            result = proposal_get(proposal_id=99999)

        _assert_error_envelope(result, expected_category="not_found", expected_retryable=False)


class TestProposalApproveMcp:
    def test_proposalApprove_happyPath_returnsApprovedProposal(self, clean_db):
        from mcp_tools.proposals import proposal_approve

        with patch("mcp_tools.proposals.proposal_service.approve", return_value=_APPROVED_PROPOSAL):
            result = proposal_approve(proposal_id=1)

        assert result["status"] == "approved"
        assert "error" not in result

    def test_proposalApprove_invalidState_returnsBusinessError(self, clean_db):
        from mcp_tools.proposals import proposal_approve

        with patch(
            "mcp_tools.proposals.proposal_service.approve",
            side_effect=ProposalServiceError(
                "already rejected", code="invalid_state", details={"current_status": "rejected"}
            ),
        ):
            result = proposal_approve(proposal_id=1)

        _assert_error_envelope(result, expected_category="business", expected_retryable=False)


class TestProposalRejectMcp:
    def test_proposalReject_happyPath_returnsRejectedProposal(self, clean_db):
        from mcp_tools.proposals import proposal_reject

        rejected = {**_PENDING_PROPOSAL, "status": "rejected", "reason": "Not needed"}
        with patch("mcp_tools.proposals.proposal_service.reject", return_value=rejected):
            result = proposal_reject(proposal_id=1, reason="Not needed")

        assert result["status"] == "rejected"
        assert "error" not in result

    def test_proposalReject_invalidState_returnsBusinessError(self, clean_db):
        from mcp_tools.proposals import proposal_reject

        with patch(
            "mcp_tools.proposals.proposal_service.reject",
            side_effect=ProposalServiceError(
                "already approved", code="invalid_state", details={"current_status": "approved"}
            ),
        ):
            result = proposal_reject(proposal_id=1, reason="too late")

        _assert_error_envelope(result, expected_category="business", expected_retryable=False)


class TestProposalResolveMcp:
    def test_proposalResolve_happyPath_returnsResolvedProposal(self, clean_db):
        from mcp_tools.proposals import proposal_resolve

        resolved = {**_PENDING_PROPOSAL, "status": "rejected"}
        with patch("mcp_tools.proposals.proposal_service.resolve", return_value=resolved):
            result = proposal_resolve(proposal_id=1)

        assert result["status"] == "rejected"
        assert "error" not in result
