"""Tests for workspace state routes."""
import pytest

from testing_utils import set_phase, add_research


def _ws_url(workspace, path):
    return f"/api/ws/{workspace['project_id']}/feature/test/{path}"


def test_get_workspace_state(client, workspace):
    response = client.get(_ws_url(workspace, "state"))
    assert response.status_code == 200
    data = response.get_json()
    assert data["phase"] == "0"
    assert "scope" in data
    assert "plan" in data
    assert "phaseHistory" in data
    assert "research" in data
    assert "progress" in data


def test_get_workspace_state_includes_source_branch_and_project_type(client, workspace):
    response = client.get(_ws_url(workspace, "state"))
    assert response.status_code == 200
    data = response.get_json()
    assert data["source_branch"] == "develop"
    assert data["project_type"] == "single"


def test_get_workspace_state_returns_etag(client, workspace):
    """State endpoint returns a stable ETag header for the JSON payload."""
    response = client.get(_ws_url(workspace, "state"))
    assert response.status_code == 200
    etag = response.headers.get("ETag")
    assert etag
    # Same request → identical etag (payload bytes are canonical).
    response2 = client.get(_ws_url(workspace, "state"))
    assert response2.headers.get("ETag") == etag


def test_get_workspace_state_304_on_matching_if_none_match(client, workspace):
    """Matching If-None-Match → 304 with empty body and the same ETag."""
    initial = client.get(_ws_url(workspace, "state"))
    etag = initial.headers.get("ETag")
    assert etag

    revalidate = client.get(_ws_url(workspace, "state"), headers={"If-None-Match": etag})
    assert revalidate.status_code == 304
    assert revalidate.headers.get("ETag") == etag
    assert revalidate.data == b""


def test_get_workspace_state_etag_changes_on_mutation(client, workspace):
    """Mutating state (changing phase) produces a different ETag and 200 response."""
    first = client.get(_ws_url(workspace, "state"))
    first_etag = first.headers.get("ETag")

    client.put(_ws_url(workspace, "phase"), json={"phase": "1.0"})

    second = client.get(_ws_url(workspace, "state"), headers={"If-None-Match": first_etag})
    assert second.status_code == 200
    second_etag = second.headers.get("ETag")
    assert second_etag
    assert second_etag != first_etag


def test_get_workspace_state_not_found(client, project):
    url = f"/api/ws/{project['id']}/feature/nonexistent/state"
    response = client.get(url)
    assert response.status_code == 404
    assert "error" in response.get_json()


def _seed_plan(client, workspace, scope):
    """Set a one-item plan at phase 2.0 so scope has an execution item to land in."""
    set_phase(workspace["id"], "2.0")
    plan = {
        "description": "",
        "systemDiagram": "",
        "execution": [{"id": "3.1", "name": "N", "scope": {"must": [], "may": []},
                       "tasks": [{"title": "T", "files": [], "agent": "a"}]}],
    }
    from mcp_server import workspace_set_plan
    import os
    cwd = os.getcwd()
    os.chdir(workspace["working_dir"])
    try:
        workspace_set_plan(plan=plan)
    finally:
        os.chdir(cwd)


def test_set_scope_echoes_payload(client, workspace):
    scope = {"3.1": {"must": ["src/"], "may": ["tests/"]}}
    response = client.put(_ws_url(workspace, "scope"), json={"scope": scope})
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["scope"] == scope


def test_set_scope_merges_into_plan_item(client, workspace):
    _seed_plan(client, workspace, scope={"must": [], "may": []})
    set_phase(workspace["id"], "3.1.0")
    scope = {"3.1": {"must": ["src/"], "may": ["tests/"]}}
    response = client.put(_ws_url(workspace, "scope"), json={"scope": scope})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    state = client.get(_ws_url(workspace, "state")).get_json()
    assert state["scope"] == scope


def test_set_scope_revokes_plan_approval(client, workspace):
    _seed_plan(client, workspace, scope={"must": [], "may": []})
    set_phase(workspace["id"], "3.1.0", plan_status="approved")
    client.put(_ws_url(workspace, "scope"), json={"scope": {"3.1": {"must": ["src/"], "may": []}}})

    state = client.get(_ws_url(workspace, "state")).get_json()
    assert state["plan_status"] == "pending"


def test_set_scope_not_found(client, project):
    url = f"/api/ws/{project['id']}/feature/nonexistent/scope"
    response = client.put(url, json={"scope": {"3.1": {"must": [], "may": []}}})
    assert response.status_code == 404
    assert "error" in response.get_json()


def test_set_phase(client, workspace):
    response = client.put(_ws_url(workspace, "phase"), json={"phase": "1.0"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["phase"] == "1.0"
    assert data["previous_phase"] == "0"

    state = client.get(_ws_url(workspace, "state")).get_json()
    history = state["phaseHistory"]
    assert len(history) == 1
    assert history[0]["from"] == "0"
    assert history[0]["to"] == "1.0"


def test_set_phase_normalizes(client, workspace):
    response = client.put(_ws_url(workspace, "phase"), json={"phase": "1"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["phase"] == "1.0"


def test_set_phase_invalid(client, workspace):
    response = client.put(_ws_url(workspace, "phase"), json={"phase": "99"})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_set_phase_rejects_bare_five(client, workspace):
    """Bare '5' is no longer a real phase (it split into 5.1/5.2/6)."""
    response = client.put(_ws_url(workspace, "phase"), json={"phase": "5"})
    assert response.status_code == 400
    assert "error" in response.get_json()


@pytest.mark.parametrize("phase", ["5.1", "5.2", "6"])
def test_set_phase_accepts_finalization_phases(client, workspace, phase):
    response = client.put(_ws_url(workspace, "phase"), json={"phase": phase})
    assert response.status_code == 200
    assert response.get_json()["phase"] == phase


def test_set_phase_rejects_unregistered_2_1(client, workspace):
    response = client.put(_ws_url(workspace, "phase"), json={"phase": "2.1"})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_set_phase_accepts_2_0(client, workspace):
    response = client.put(_ws_url(workspace, "phase"), json={"phase": "2.0"})
    assert response.status_code == 200
    assert response.get_json()["phase"] == "2.0"


def test_set_phase_not_found(client, project):
    url = f"/api/ws/{project['id']}/feature/nonexistent/phase"
    response = client.put(url, json={"phase": "1.0"})
    assert response.status_code == 404
    assert "error" in response.get_json()


def test_toggle_research_proven(client, workspace):
    research_id = add_research(workspace["id"], topic="Auth flow", proven=0)
    url = _ws_url(workspace, f"research/{research_id}/prove")
    response = client.post(url, json={"proven": True})
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["id"] == research_id
    assert data["proven"] == 1


def test_delete_research(client, workspace):
    research_id = add_research(workspace["id"])

    response = client.delete(_ws_url(workspace, f"research/{research_id}"))
    assert response.status_code == 200
    assert response.get_json()["ok"]

    state = client.get(_ws_url(workspace, "state")).get_json()
    assert all(entry["id"] != research_id for entry in state["research"])


def test_delete_research_not_found(client, workspace):
    response = client.delete(_ws_url(workspace, "research/99999"))
    assert response.status_code == 404


def test_set_plan_status(client, workspace):
    r = client.post("/api/ws/test-project/feature/test/plan-status", json={"status": "approved"})
    assert r.status_code == 200
    assert r.json["plan_status"] == "approved"


def test_set_plan_status_invalid(client, workspace):
    r = client.post("/api/ws/test-project/feature/test/plan-status", json={"status": "invalid"})
    assert r.status_code == 400


def _criteria_statuses(ws_id):
    from core.db import get_db
    db = get_db()
    try:
        rows = db.execute(
            "SELECT status FROM acceptance_criteria WHERE workspace_id = ? ORDER BY id",
            (ws_id,)
        ).fetchall()
        return [row["status"] for row in rows]
    finally:
        db.close()


def test_approve_plan_cascades_proposed_criteria_to_accepted(client, workspace):
    from testing_utils import add_criterion
    add_criterion(workspace["id"], status="proposed")
    add_criterion(workspace["id"], status="proposed")

    r = client.post("/api/ws/test-project/feature/test/plan-status", json={"status": "approved"})
    assert r.status_code == 200

    assert _criteria_statuses(workspace["id"]) == ["accepted", "accepted"]


def test_approve_plan_cascade_is_idempotent_when_none_proposed(client, workspace):
    from testing_utils import add_criterion
    add_criterion(workspace["id"], status="accepted")

    client.post("/api/ws/test-project/feature/test/plan-status", json={"status": "approved"})
    r = client.post("/api/ws/test-project/feature/test/plan-status", json={"status": "approved"})
    assert r.status_code == 200

    assert _criteria_statuses(workspace["id"]) == ["accepted"]


def test_reject_plan_does_not_accept_proposed_criteria(client, workspace):
    from testing_utils import add_criterion
    add_criterion(workspace["id"], status="proposed")

    r = client.post("/api/ws/test-project/feature/test/plan-status", json={"status": "rejected"})
    assert r.status_code == 200

    assert _criteria_statuses(workspace["id"]) == ["proposed"]


def test_state_payload_has_no_scope_status(client, workspace):
    state = client.get(_ws_url(workspace, "state")).get_json()
    assert "scope_status" not in state
    assert "scope" in state


def test_mcp_get_state_exposes_standard_workflow_mode(workspace, monkeypatch):
    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_get_state
    result = workspace_get_state()
    assert result["workflow_mode"] == "standard"


def test_mcp_get_state_exposes_fast_workflow_mode_and_omits_optional_phases(workspace, monkeypatch):
    from core.db import get_db
    from services.workflow_mode_service import apply_mode_phase_settings

    db = get_db()
    try:
        apply_mode_phase_settings(db, workspace["id"], "fast")
        db.execute("UPDATE workspaces SET workflow_mode = 'fast' WHERE id = ?", (workspace["id"],))
        db.commit()
    finally:
        db.close()

    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_get_state
    result = workspace_get_state()

    assert result["workflow_mode"] == "fast"
    for phase_id in ("1.3", "1.4", "4.0"):
        assert phase_id not in result["phase_sequence"]

