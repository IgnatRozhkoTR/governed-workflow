"""HTTP route tests for work-modes and workspace work-mode assignment (sub-phase 3.6)."""
import pytest

from core.db import get_db


@pytest.fixture
def basic_mode_id(clean_db):
    db = get_db()
    try:
        row = db.execute("SELECT id FROM work_modes WHERE name = 'basic'").fetchone()
        return row["id"]
    finally:
        db.close()


@pytest.fixture
def user_mode(client):
    resp = client.post("/api/work-modes", json={"name": "route-test-mode", "description": "test"})
    assert resp.status_code == 201
    return resp.get_json()


# ── GET /api/work-modes ───────────────────────────────────────────────────────

def test_list_modes_returns_200_with_basic(client):
    resp = client.get("/api/work-modes")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    names = {m["name"] for m in data}
    assert "basic" in names


# ── POST /api/work-modes ──────────────────────────────────────────────────────

def test_create_mode_returns_201_with_body(client):
    resp = client.post("/api/work-modes", json={
        "name": "audit-only",
        "description": "Audit workflow",
        "phases": [{"phase_id": "1.1", "enabled": True, "position": 0}],
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"] == "audit-only"
    assert data["origin"] == "user"
    assert isinstance(data["id"], int)


def test_create_mode_name_collision_returns_409(client, user_mode):
    resp = client.post("/api/work-modes", json={"name": user_mode["name"]})
    assert resp.status_code == 409
    assert "error" in resp.get_json()


def test_create_mode_invalid_name_returns_400(client):
    resp = client.post("/api/work-modes", json={"name": "bad name with spaces"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


# ── GET /api/work-modes/<id> ──────────────────────────────────────────────────

def test_get_mode_returns_200(client, user_mode):
    resp = client.get(f"/api/work-modes/{user_mode['id']}")
    assert resp.status_code == 200
    assert resp.get_json()["id"] == user_mode["id"]


def test_get_mode_unknown_returns_404(client):
    resp = client.get("/api/work-modes/999999")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


# ── PATCH /api/work-modes/<id> ────────────────────────────────────────────────

def test_patch_mode_returns_200(client, user_mode):
    resp = client.patch(
        f"/api/work-modes/{user_mode['id']}",
        json={"description": "updated"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["description"] == "updated"


def test_patch_system_mode_returns_409(client, basic_mode_id):
    resp = client.patch(
        f"/api/work-modes/{basic_mode_id}",
        json={"description": "hacked"},
    )
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["code"] == "system_immutable"


# ── DELETE /api/work-modes/<id> ───────────────────────────────────────────────

def test_delete_user_mode_returns_200(client, user_mode):
    resp = client.delete(f"/api/work-modes/{user_mode['id']}")
    assert resp.status_code == 200
    assert resp.get_json()["id"] == user_mode["id"]

    get_resp = client.get(f"/api/work-modes/{user_mode['id']}")
    assert get_resp.status_code == 404


def test_delete_system_mode_returns_409(client, basic_mode_id):
    resp = client.delete(f"/api/work-modes/{basic_mode_id}")
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["code"] == "system_immutable"


# ── PUT /api/workspaces/<id>/work-mode ────────────────────────────────────────

def test_assign_mode_returns_200_with_mode_id(client, workspace, basic_mode_id):
    resp = client.put(
        f"/api/workspaces/{workspace['id']}/work-mode",
        json={"mode_id": basic_mode_id},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["workspace_id"] == workspace["id"]
    assert data["mode_id"] == basic_mode_id


def test_assign_mode_missing_mode_id_returns_400(client, workspace):
    resp = client.put(
        f"/api/workspaces/{workspace['id']}/work-mode",
        json={},
    )
    assert resp.status_code == 400


def test_assign_mode_unknown_workspace_returns_404(client, basic_mode_id):
    resp = client.put(
        "/api/workspaces/999999/work-mode",
        json={"mode_id": basic_mode_id},
    )
    assert resp.status_code == 404


# ── POST /api/workspaces/<id>/work-mode/apply ─────────────────────────────────

def test_apply_mode_returns_200_with_effective_phases(client, workspace):
    resp = client.post(f"/api/workspaces/{workspace['id']}/work-mode/apply")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "effective_phases" in data
    assert isinstance(data["effective_phases"], list)
    assert len(data["effective_phases"]) > 0


def test_apply_mode_unknown_workspace_returns_404(client):
    resp = client.post("/api/workspaces/999999/work-mode/apply")
    assert resp.status_code == 404
