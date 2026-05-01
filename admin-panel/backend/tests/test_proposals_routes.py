"""Tests for proposal REST endpoints under /api/proposals."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.proposal_service import ProposalServiceError


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

_EXECUTED_PROPOSAL = {**_PENDING_PROPOSAL, "status": "executed", "result": {"ok": True}}
_REJECTED_PROPOSAL = {**_PENDING_PROPOSAL, "status": "rejected", "reason": "Not needed"}


class TestCreateProposalRoute:
    def test_post_createsPendingProposal_returns201(self, client):
        with patch(
            "routes.proposals.proposal_service.create",
            return_value=_PENDING_PROPOSAL,
        ):
            response = client.post(
                "/api/proposals",
                json={
                    "type": "memory_write",
                    "title": "Save a note",
                    "payload": {"content": "hello"},
                },
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "pending"
        assert data["type"] == "memory_write"

    def test_post_invalidType_returns400(self, client):
        with patch(
            "routes.proposals.proposal_service.create",
            side_effect=ProposalServiceError("unknown type", code="invalid_type"),
        ):
            response = client.post(
                "/api/proposals",
                json={"type": "totally_bogus", "title": "Bad"},
            )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "invalid_type"

    def test_post_invalidPayload_returns400(self, client):
        with patch(
            "routes.proposals.proposal_service.create",
            side_effect=ProposalServiceError("not a dict", code="invalid_payload"),
        ):
            response = client.post(
                "/api/proposals",
                json={"type": "memory_write", "title": "Test", "payload": "not-a-dict"},
            )

        assert response.status_code == 400


class TestListProposalsRoute:
    def test_get_listReturnsProposals(self, client):
        with patch(
            "routes.proposals.proposal_service.list_proposals",
            return_value=[_PENDING_PROPOSAL],
        ):
            response = client.get("/api/proposals")

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert data[0]["id"] == 1

    def test_get_filtersPassedToService(self, client):
        captured = {}

        def _capture_list(db, status=None, type=None, workspace_id=None, project_id=None, origin=None):
            captured.update({"status": status, "type": type})
            return []

        with patch("routes.proposals.proposal_service.list_proposals", side_effect=_capture_list):
            client.get("/api/proposals?status=pending&type=memory_write")

        assert captured["status"] == "pending"
        assert captured["type"] == "memory_write"

    def test_get_proposals_filters_by_origin_query_param(self, client, clean_db):
        from core.db import get_db
        from services.proposal_service import create

        db = get_db()
        try:
            create(db, type="memory_write", title="From reflection", origin="reflection")
            create(db, type="rule_new", title="From agent", origin="agent")
            create(db, type="workflow_improvement", title="Also from reflection", origin="reflection")
        finally:
            db.close()

        response = client.get("/api/proposals?origin=reflection")

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert all(item["origin"] == "reflection" for item in data)


class TestGetProposalRoute:
    def test_get_returnsProposal_byId(self, client):
        with patch(
            "routes.proposals.proposal_service.get",
            return_value=_PENDING_PROPOSAL,
        ):
            response = client.get("/api/proposals/1")

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == 1

    def test_get_returns404_whenNotFound(self, client):
        with patch(
            "routes.proposals.proposal_service.get",
            side_effect=ProposalServiceError("not found", code="not_found"),
        ):
            response = client.get("/api/proposals/99999")

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "not_found"


class TestApproveProposalRoute:
    def test_post_approve_happyPath_returns200(self, client):
        with patch(
            "routes.proposals.proposal_service.approve",
            return_value=_EXECUTED_PROPOSAL,
        ):
            response = client.post("/api/proposals/1/approve")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "executed"

    def test_post_approve_invalidState_returns409(self, client):
        with patch(
            "routes.proposals.proposal_service.approve",
            side_effect=ProposalServiceError(
                "already rejected", code="invalid_state", details={"current_status": "rejected"}
            ),
        ):
            response = client.post("/api/proposals/1/approve")

        assert response.status_code == 409
        data = response.get_json()
        assert data["code"] == "invalid_state"

    def test_post_approve_executionFailed_returns500(self, client):
        with patch(
            "routes.proposals.proposal_service.approve",
            side_effect=ProposalServiceError(
                "execution failed", code="execution_failed",
                details={"underlying_code": "not_found"},
            ),
        ):
            response = client.post("/api/proposals/1/approve")

        assert response.status_code == 500


class TestRejectProposalRoute:
    def test_post_reject_happyPath_returns200(self, client):
        with patch(
            "routes.proposals.proposal_service.reject",
            return_value=_REJECTED_PROPOSAL,
        ):
            response = client.post(
                "/api/proposals/1/reject",
                json={"reason": "Not needed"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "rejected"

    def test_post_reject_invalidState_returns409(self, client):
        with patch(
            "routes.proposals.proposal_service.reject",
            side_effect=ProposalServiceError(
                "already executed", code="invalid_state", details={"current_status": "executed"}
            ),
        ):
            response = client.post(
                "/api/proposals/1/reject",
                json={"reason": "too late"},
            )

        assert response.status_code == 409


class TestResolveProposalRoute:
    def test_post_resolve_happyPath_returns200(self, client):
        resolved = {**_PENDING_PROPOSAL, "status": "rejected"}
        with patch(
            "routes.proposals.proposal_service.resolve",
            return_value=resolved,
        ):
            response = client.post("/api/proposals/1/resolve")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "rejected"

    def test_post_resolve_invalidState_returns409_forExecuted(self, client):
        with patch(
            "routes.proposals.proposal_service.resolve",
            side_effect=ProposalServiceError(
                "already executed", code="invalid_state", details={"current_status": "executed"}
            ),
        ):
            response = client.post("/api/proposals/1/resolve")

        assert response.status_code == 409
        data = response.get_json()
        assert data["code"] == "invalid_state"
