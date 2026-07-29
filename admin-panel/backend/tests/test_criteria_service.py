"""Tests for criteria_service.delete_criterion / get_criterion.

Deletion has no status guard at the service layer — the accepted-criterion
restriction is enforced one layer up, inside the MCP tool, so the human's
admin panel keeps the ability to delete any criterion.
"""
from core.db import get_db
from services import criteria_service
from testing_utils import add_criterion


def test_delete_criterion_deletes_accepted_criterion(workspace):
    criterion_id = add_criterion(workspace["id"], status="accepted")

    db = get_db()
    try:
        result = criteria_service.delete_criterion(db, criterion_id, workspace["id"])
        db.commit()
    finally:
        db.close()

    assert result == {"ok": True}

    db = get_db()
    try:
        assert criteria_service.get_criterion(db, criterion_id, workspace["id"]) is None
    finally:
        db.close()


def test_delete_criterion_returns_not_found_for_unknown_id(workspace):
    db = get_db()
    try:
        result = criteria_service.delete_criterion(db, 987654, workspace["id"])
    finally:
        db.close()

    assert result == {"error": "criterion_not_found"}


def test_get_criterion_returns_none_for_unknown_id(workspace):
    db = get_db()
    try:
        result = criteria_service.get_criterion(db, 987654, workspace["id"])
    finally:
        db.close()

    assert result is None


def test_get_criterion_returns_criterion_scoped_to_workspace(workspace):
    criterion_id = add_criterion(workspace["id"], description="Scoped check")

    db = get_db()
    try:
        result = criteria_service.get_criterion(db, criterion_id, workspace["id"])
    finally:
        db.close()

    assert result["id"] == criterion_id
    assert result["description"] == "Scoped check"
