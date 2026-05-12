"""End-to-end integration tests for the proposal lifecycle.

The proposal subsystem is text-only — approval is a status flip, no execution.
These tests cover the full pipeline: create → approve (status flip) → list visibility.
"""
from core.db import get_db
from services import proposal_service


def test_proposal_lifecycle_create_approve_list_visibility(clean_db):
    db = get_db()
    try:
        proposal = proposal_service.create(
            db,
            type="memory_write",
            title="Save snippet",
            body="Important note for later.",
            payload={},
        )

        approved = proposal_service.approve(db, proposal["id"])

        approved_listing = proposal_service.list_proposals(db, status="approved")
        pending_listing = proposal_service.list_proposals(db, status="pending")
    finally:
        db.close()

    assert approved["status"] == "approved"
    assert approved["reviewed_at"] is not None
    assert approved["id"] == proposal["id"]

    assert len(approved_listing) == 1
    assert approved_listing[0]["id"] == proposal["id"]
    assert approved_listing[0]["title"] == "Save snippet"

    assert pending_listing == []


def test_proposal_lifecycle_create_reject_list_visibility(clean_db):
    db = get_db()
    try:
        proposal = proposal_service.create(
            db,
            type="rule_new",
            title="Add a rule",
            body="Some recommendation.",
            payload={},
        )

        rejected = proposal_service.reject(db, proposal["id"], "Not relevant.")

        rejected_listing = proposal_service.list_proposals(db, status="rejected")
        pending_listing = proposal_service.list_proposals(db, status="pending")
    finally:
        db.close()

    assert rejected["status"] == "rejected"
    assert rejected["reason"] == "Not relevant."

    assert len(rejected_listing) == 1
    assert rejected_listing[0]["id"] == proposal["id"]

    assert pending_listing == []


def test_proposal_approve_idempotent_keeps_status_approved(clean_db):
    db = get_db()
    try:
        proposal = proposal_service.create(
            db,
            type="workflow_improvement",
            title="Iterate",
            body="Refine workflow.",
        )

        first = proposal_service.approve(db, proposal["id"])
        second = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert first["status"] == "approved"
    assert second["status"] == "approved"
    assert first["id"] == second["id"]
