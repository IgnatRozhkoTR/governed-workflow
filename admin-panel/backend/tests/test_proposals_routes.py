"""Tests for the proposals REST routes (list and resolve)."""
from core.db import get_db
from services.proposal_service import create_proposal

BASE = "/api/ws/test-project/feature/test/proposals"


def _seed(workspace, **kwargs):
    """Create a proposal row and return its id."""
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


def test_list_proposals_returns_both_proposals_newest_first(client, workspace):
    pid1 = _seed(workspace, title="First")
    pid2 = _seed(workspace, title="Second")

    r = client.get(BASE)

    assert r.status_code == 200
    proposals = r.json["proposals"]
    assert len(proposals) == 2
    ids = [p["id"] for p in proposals]
    assert ids == sorted(ids, reverse=True)
    assert {p["id"] for p in proposals} == {pid1, pid2}


def test_list_proposals_filters_by_status(client, workspace):
    _seed(workspace, title="Open proposal")
    resolved_id = _seed(workspace, title="Resolved proposal")
    client.put(f"{BASE}/{resolved_id}/resolve", json={"status": "executed"})

    r = client.get(BASE, query_string={"status": "proposed"})

    assert r.status_code == 200
    proposals = r.json["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["status"] == "proposed"


def test_list_proposals_returns_400_for_invalid_status(client, workspace):
    r = client.get(BASE, query_string={"status": "bogus"})

    assert r.status_code == 400
    assert "error" in r.json


def test_resolve_proposal_transitions_to_executed(client, workspace):
    pid = _seed(workspace, title="To execute")

    r = client.put(f"{BASE}/{pid}/resolve", json={"status": "executed"})

    assert r.status_code == 200
    assert r.json["status"] == "executed"

    r2 = client.get(BASE, query_string={"status": "executed"})
    assert any(p["id"] == pid for p in r2.json["proposals"])


def test_resolve_proposal_transitions_to_rejected(client, workspace):
    pid = _seed(workspace, title="To reject")

    r = client.put(f"{BASE}/{pid}/resolve", json={"status": "rejected"})

    assert r.status_code == 200
    assert r.json["status"] == "rejected"


def test_resolve_proposal_returns_404_for_missing_id(client, workspace):
    r = client.put(f"{BASE}/999999/resolve", json={"status": "executed"})

    assert r.status_code == 404
    assert "error" in r.json


def test_resolve_proposal_returns_409_when_already_resolved(client, workspace):
    pid = _seed(workspace, title="Already done")
    client.put(f"{BASE}/{pid}/resolve", json={"status": "executed"})

    r = client.put(f"{BASE}/{pid}/resolve", json={"status": "rejected"})

    assert r.status_code == 409
    assert "error" in r.json
