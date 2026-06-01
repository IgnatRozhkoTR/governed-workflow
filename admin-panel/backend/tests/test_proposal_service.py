"""Tests for proposal_service CRUD operations."""
import pytest

from core.db import get_db
from services.proposal_service import (
    ProposalServiceError,
    create_proposal,
    get_proposal,
    list_proposals,
)


def _create(workspace, **kwargs):
    """Helper: create a proposal with sensible defaults and return its id."""
    defaults = {
        "type": "rule_new",
        "implementation_kind": "manual",
        "title": "Test proposal",
        "body": "Some body",
    }
    defaults.update(kwargs)
    db = get_db()
    try:
        return create_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=workspace["project_id"],
            **defaults,
        )
    finally:
        db.close()


def test_create_proposal_inserts_row_with_proposed_status(workspace):
    proposal_id = _create(workspace)

    db = get_db()
    try:
        row = db.execute(
            "SELECT status FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
    finally:
        db.close()

    assert row is not None
    assert row["status"] == "proposed"


def test_create_proposal_returns_new_id(workspace):
    proposal_id = _create(workspace)

    assert isinstance(proposal_id, int)
    assert proposal_id > 0


def test_create_proposal_raises_when_implementation_kind_invalid(workspace):
    db = get_db()
    try:
        with pytest.raises(ProposalServiceError) as exc_info:
            create_proposal(
                db,
                workspace_id=workspace["id"],
                project_id=workspace["project_id"],
                type="rule_new",
                implementation_kind="robot",
                title="Bad kind",
                body="",
            )
    finally:
        db.close()

    assert exc_info.value.code == "invalid_implementation_kind"


def test_create_proposal_raises_when_type_invalid(workspace):
    db = get_db()
    try:
        with pytest.raises(ProposalServiceError) as exc_info:
            create_proposal(
                db,
                workspace_id=workspace["id"],
                project_id=workspace["project_id"],
                type="delete_everything",
                implementation_kind="manual",
                title="Bad type",
                body="",
            )
    finally:
        db.close()

    assert exc_info.value.code == "invalid_proposal_type"


def test_list_proposals_returns_rows_for_workspace_only(workspace, second_workspace):
    _create(workspace, title="Workspace 1 proposal")
    _create(second_workspace, title="Workspace 2 proposal")

    db = get_db()
    try:
        rows = list_proposals(db, workspace_id=workspace["id"])
    finally:
        db.close()

    assert len(rows) == 1
    assert rows[0]["title"] == "Workspace 1 proposal"
    assert rows[0]["workspace_id"] == workspace["id"]


def test_list_proposals_returns_empty_list_when_no_rows(workspace):
    db = get_db()
    try:
        rows = list_proposals(db, workspace_id=workspace["id"])
    finally:
        db.close()

    assert rows == []


def test_get_proposal_returns_none_when_missing(workspace):
    db = get_db()
    try:
        result = get_proposal(db, proposal_id=999999)
    finally:
        db.close()

    assert result is None
