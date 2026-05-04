"""Tests for proposal_service: CRUD and pure status-flip lifecycle.

The proposal subsystem is text-only — approval is a status flip, no execution.
"""
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.proposal_service import (
    PROPOSAL_TYPES,
    ProposalServiceError,
    create,
    approve,
    get,
    list_proposals,
    reject,
    resolve,
)


_EXPECTED_TYPES = {
    "memory_write",
    "memory_delete",
    "rule_new",
    "rule_update",
    "agent_new",
    "agent_update",
    "skill_new",
    "skill_update",
    "workflow_improvement",
}


def _db():
    from core.db import get_db
    return get_db()


def _create_pending(db, type_="memory_write", title="Test proposal", payload=None):
    return create(
        db,
        type=type_,
        title=title,
        payload=payload or {},
    )


class TestProposalTypes:
    def test_proposalTypes_containsExactlyNineExpectedStrings(self):
        assert PROPOSAL_TYPES == _EXPECTED_TYPES


class TestCreateProposal:
    def test_create_storesPendingProposal_withPayloadJson(self, clean_db):
        db = _db()
        try:
            result = create(
                db,
                type="memory_write",
                title="Save a memory",
                payload={"some": "metadata"},
            )
        finally:
            db.close()

        assert result["type"] == "memory_write"
        assert result["status"] == "pending"
        assert result["title"] == "Save a memory"
        assert result["payload"] == {"some": "metadata"}

    def test_create_acceptsEmptyPayload(self, clean_db):
        db = _db()
        try:
            result = create(
                db,
                type="memory_write",
                title="Body-only",
                body="Read this and decide.",
            )
        finally:
            db.close()

        assert result["payload"] == {}
        assert result["body"] == "Read this and decide."

    def test_create_raises_invalidType_forUnknownType(self, clean_db):
        db = _db()
        try:
            with pytest.raises(ProposalServiceError) as exc_info:
                create(db, type="not_a_type", title="Test")
        finally:
            db.close()

        assert exc_info.value.code == "invalid_type"

    def test_create_raises_invalidPayload_whenPayloadNotDict(self, clean_db):
        db = _db()
        try:
            with pytest.raises(ProposalServiceError) as exc_info:
                create(db, type="memory_write", title="Test", payload="not-a-dict")
        finally:
            db.close()

        assert exc_info.value.code == "invalid_payload"

    def test_create_raises_invalidPayload_whenTitleEmpty(self, clean_db):
        db = _db()
        try:
            with pytest.raises(ProposalServiceError) as exc_info:
                create(db, type="memory_write", title="   ")
        finally:
            db.close()

        assert exc_info.value.code == "invalid_payload"

    def test_create_storesOriginAndIds(self, clean_db):
        db = _db()
        try:
            result = create(
                db,
                type="rule_new",
                title="New rule",
                origin="reflection",
                workspace_id=None,
                project_id=None,
            )
        finally:
            db.close()

        assert result["origin"] == "reflection"
        assert result["id"] is not None


class TestListProposals:
    def test_list_returnsAll_whenNoFilters(self, clean_db):
        db = _db()
        try:
            _create_pending(db, type_="memory_write", title="First")
            _create_pending(db, type_="rule_new", title="Second")

            result = list_proposals(db)
        finally:
            db.close()

        assert len(result) == 2

    def test_list_filtersByStatus(self, clean_db):
        db = _db()
        try:
            _create_pending(db, title="Pending one")
            p2 = _create_pending(db, title="To reject")
            reject(db, p2["id"], "not needed")

            result = list_proposals(db, status="pending")
        finally:
            db.close()

        assert all(r["status"] == "pending" for r in result)
        assert len(result) == 1

    def test_list_filtersByType(self, clean_db):
        db = _db()
        try:
            _create_pending(db, type_="memory_write", title="Memory one")
            _create_pending(db, type_="rule_new", title="Rule one")

            result = list_proposals(db, type="rule_new")
        finally:
            db.close()

        assert all(r["type"] == "rule_new" for r in result)
        assert len(result) == 1

    def test_list_filtersByWorkspaceId(self, clean_db, workspace):
        db = _db()
        try:
            create(db, type="memory_write", title="ws-scoped", workspace_id=workspace["id"])
            create(db, type="memory_write", title="unscoped")

            result = list_proposals(db, workspace_id=workspace["id"])
        finally:
            db.close()

        assert len(result) == 1
        assert result[0]["title"] == "ws-scoped"

    def test_list_proposals_filter_by_origin(self, clean_db):
        db = _db()
        try:
            create(db, type="memory_write", title="Reflection note", origin="reflection")
            create(db, type="rule_new", title="Agent rule", origin="agent")
            create(db, type="workflow_improvement", title="Reflection improvement", origin="reflection")

            result = list_proposals(db, origin="reflection")
        finally:
            db.close()

        assert len(result) == 2
        assert all(r["origin"] == "reflection" for r in result)
        titles = {r["title"] for r in result}
        assert titles == {"Reflection note", "Reflection improvement"}


class TestGetProposal:
    def test_get_returnsProposal_byId(self, clean_db):
        db = _db()
        try:
            created = _create_pending(db, title="My proposal")

            result = get(db, created["id"])
        finally:
            db.close()

        assert result["id"] == created["id"]
        assert result["title"] == "My proposal"

    def test_get_raises_notFound_forUnknownId(self, clean_db):
        db = _db()
        try:
            with pytest.raises(ProposalServiceError) as exc_info:
                get(db, 99999)
        finally:
            db.close()

        assert exc_info.value.code == "not_found"


class TestApproveProposal:
    def test_approve_pendingProposal_flipsStatusAndStampsReviewedAt(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)

            result = approve(db, proposal["id"])
        finally:
            db.close()

        assert result["status"] == "approved"
        assert result["reviewed_at"] is not None
        assert result["id"] == proposal["id"]

    def test_approve_idempotent_returnsCurrentRow_whenAlreadyApproved(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)
            first = approve(db, proposal["id"])

            second = approve(db, proposal["id"])
        finally:
            db.close()

        assert first["status"] == "approved"
        assert second["status"] == "approved"
        assert second["id"] == first["id"]

    def test_approve_raises_invalidState_forRejectedProposal(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)
            reject(db, proposal["id"], "not needed")

            with pytest.raises(ProposalServiceError) as exc_info:
                approve(db, proposal["id"])
        finally:
            db.close()

        assert exc_info.value.code == "invalid_state"

    def test_approve_isAtomic_doesNotRevertOnAlreadyApprovedConcurrent(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)

            db.execute(
                "UPDATE proposals SET status = 'approved', reviewed_at = '2024-01-01T00:00:00' WHERE id = ?",
                (proposal["id"],),
            )
            db.commit()

            result = approve(db, proposal["id"])
        finally:
            db.close()

        assert result["status"] == "approved"
        assert result["reviewed_at"] == "2024-01-01T00:00:00"


class TestRejectProposal:
    def test_reject_setsStatusRejected_withReason(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)

            result = reject(db, proposal["id"], "Not relevant anymore")
        finally:
            db.close()

        assert result["status"] == "rejected"
        assert result["reason"] == "Not relevant anymore"

    def test_reject_raises_invalidState_forApprovedProposal(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)
            approve(db, proposal["id"])

            with pytest.raises(ProposalServiceError) as exc_info:
                reject(db, proposal["id"], "too late")
        finally:
            db.close()

        assert exc_info.value.code == "invalid_state"

    def test_reject_idempotent_returnsCurrentRow_forAlreadyRejected(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)
            reject(db, proposal["id"], "first reason")

            result = reject(db, proposal["id"], "second reason")
        finally:
            db.close()

        assert result["status"] == "rejected"

    def test_reject_raises_invalidPayload_whenReasonEmpty(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)

            with pytest.raises(ProposalServiceError) as exc_info:
                reject(db, proposal["id"], "  ")
        finally:
            db.close()

        assert exc_info.value.code == "invalid_payload"


class TestResolveProposal:
    def test_resolve_setsStatusRejected_forApprovedProposal(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)
            approve(db, proposal["id"])

            result = resolve(db, proposal["id"])
        finally:
            db.close()

        assert result["status"] == "rejected"

    def test_resolve_setsStatusRejected_forPendingProposal(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)

            result = resolve(db, proposal["id"])
        finally:
            db.close()

        assert result["status"] == "rejected"

    def test_resolve_idempotent_forAlreadyRejected(self, clean_db):
        db = _db()
        try:
            proposal = _create_pending(db)
            reject(db, proposal["id"], "rejected first")

            result = resolve(db, proposal["id"])
        finally:
            db.close()

        assert result["status"] == "rejected"
