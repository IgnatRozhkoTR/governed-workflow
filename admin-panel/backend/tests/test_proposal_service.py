"""Tests for proposal_service CRUD operations."""
import pytest

from core.db import get_db
from services.proposal_service import (
    ProposalServiceError,
    create_proposal,
    get_proposal,
    list_proposals,
    reject_open_proposals,
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


# ---------------------------------------------------------------------------
# list_proposals filters
# ---------------------------------------------------------------------------

def test_list_proposals_filters_by_implementation_kind(workspace):
    _create(workspace, implementation_kind="auto", title="Auto proposal")
    _create(workspace, implementation_kind="manual", title="Manual proposal")

    db = get_db()
    try:
        rows = list_proposals(db, workspace_id=workspace["id"], implementation_kind="auto")
    finally:
        db.close()

    assert len(rows) == 1
    assert rows[0]["title"] == "Auto proposal"
    assert rows[0]["implementation_kind"] == "auto"


def test_list_proposals_filters_by_status(workspace):
    from services.proposal_service import resolve_proposal
    proposal_id = _create(workspace, title="To be resolved")

    db = get_db()
    try:
        resolve_proposal(db, proposal_id, status="executed")
        db.commit()
        rows = list_proposals(db, workspace_id=workspace["id"], status="executed")
    finally:
        db.close()

    assert len(rows) == 1
    assert rows[0]["id"] == proposal_id
    assert rows[0]["status"] == "executed"


def test_list_proposals_raises_when_filter_invalid(workspace):
    from services.proposal_service import ProposalServiceError
    db = get_db()
    try:
        with pytest.raises(ProposalServiceError) as exc_info:
            list_proposals(db, workspace_id=workspace["id"], implementation_kind="robot")
    finally:
        db.close()

    assert exc_info.value.code == "invalid_argument"


# ---------------------------------------------------------------------------
# resolve_proposal
# ---------------------------------------------------------------------------

def test_resolve_proposal_sets_executed_status_and_timestamp(workspace):
    from services.proposal_service import resolve_proposal
    proposal_id = _create(workspace)

    db = get_db()
    try:
        updated = resolve_proposal(db, proposal_id, status="executed")
        db.commit()
    finally:
        db.close()

    assert updated["status"] == "executed"
    assert updated["executed_at"] is not None
    assert updated["reviewed_at"] is None


def test_resolve_proposal_sets_rejected_reviewed_at(workspace):
    from services.proposal_service import resolve_proposal
    proposal_id = _create(workspace)

    db = get_db()
    try:
        updated = resolve_proposal(db, proposal_id, status="rejected")
        db.commit()
    finally:
        db.close()

    assert updated["status"] == "rejected"
    assert updated["reviewed_at"] is not None
    assert updated["executed_at"] is None


def test_resolve_proposal_persists_result_json(workspace):
    from services.proposal_service import resolve_proposal
    proposal_id = _create(workspace)
    result = '{"summary": "applied"}'

    db = get_db()
    try:
        updated = resolve_proposal(db, proposal_id, status="executed", result_json=result)
        db.commit()
    finally:
        db.close()

    assert updated["result_json"] == result


def test_resolve_proposal_raises_when_missing(workspace):
    from services.proposal_service import ProposalServiceError, resolve_proposal
    db = get_db()
    try:
        with pytest.raises(ProposalServiceError) as exc_info:
            resolve_proposal(db, 999999, status="executed")
    finally:
        db.close()

    assert exc_info.value.code == "proposal_not_found"


# ---------------------------------------------------------------------------
# count_pending_manual_proposals
# ---------------------------------------------------------------------------

def test_count_pending_manual_proposals_returns_correct_count(workspace):
    from services.proposal_service import count_pending_manual_proposals
    _create(workspace, implementation_kind="manual")
    _create(workspace, implementation_kind="manual")
    _create(workspace, implementation_kind="auto")

    db = get_db()
    try:
        count = count_pending_manual_proposals(db, workspace["id"])
    finally:
        db.close()

    assert count == 2


def test_count_pending_manual_proposals_returns_zero_when_none(workspace):
    from services.proposal_service import count_pending_manual_proposals
    db = get_db()
    try:
        count = count_pending_manual_proposals(db, workspace["id"])
    finally:
        db.close()

    assert count == 0


# ---------------------------------------------------------------------------
# ALLOWED_STATUSES tightening — 'pending' and 'approved' are no longer valid
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("removed_status", ["pending", "approved"])
def test_list_proposals_raises_when_status_is_scaffolding_value(workspace, removed_status):
    db = get_db()
    try:
        with pytest.raises(ProposalServiceError) as exc_info:
            list_proposals(db, workspace_id=workspace["id"], status=removed_status)
    finally:
        db.close()

    assert exc_info.value.code == "invalid_argument"


# ---------------------------------------------------------------------------
# reject_open_proposals
# ---------------------------------------------------------------------------

def test_reject_open_proposals_returns_count_of_affected_rows(workspace):
    _create(workspace, title="Proposal A")
    _create(workspace, title="Proposal B")

    db = get_db()
    try:
        count = reject_open_proposals(db, workspace["id"])
        db.commit()
    finally:
        db.close()

    assert count == 2


def test_reject_open_proposals_sets_status_reason_and_reviewed_at(workspace):
    proposal_id = _create(workspace, title="Open proposal")

    db = get_db()
    try:
        reject_open_proposals(db, workspace["id"])
        db.commit()
        row = db.execute(
            "SELECT status, reason, reviewed_at FROM proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    finally:
        db.close()

    assert row["status"] == "rejected"
    assert row["reason"] == "Workspace archived"
    assert row["reviewed_at"] is not None


def test_reject_open_proposals_does_not_affect_other_workspace(workspace, second_workspace):
    _create(workspace, title="Workspace 1 proposal")
    _create(second_workspace, title="Workspace 2 proposal")

    db = get_db()
    try:
        count = reject_open_proposals(db, workspace["id"])
        db.commit()
        remaining = list_proposals(db, workspace_id=second_workspace["id"])
    finally:
        db.close()

    assert count == 1
    assert len(remaining) == 1
    assert remaining[0]["status"] == "proposed"


def test_reject_open_proposals_skips_already_terminal_rows(workspace):
    from services.proposal_service import resolve_proposal
    proposal_id = _create(workspace, title="Already done")

    db = get_db()
    try:
        resolve_proposal(db, proposal_id, status="executed")
        db.commit()
        count = reject_open_proposals(db, workspace["id"])
        db.commit()
    finally:
        db.close()

    assert count == 0


def test_reject_open_proposals_returns_zero_when_no_open_proposals(workspace):
    db = get_db()
    try:
        count = reject_open_proposals(db, workspace["id"])
        db.commit()
    finally:
        db.close()

    assert count == 0
