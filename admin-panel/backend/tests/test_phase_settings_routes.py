"""Integration tests for phase-settings HTTP routes (phase 3.3)."""
import pytest


# ── GET / PUT round-trip ──────────────────────────────────────────────────────

def test_get_device_empty(client):
    response = client.get("/api/phase-settings/device")
    assert response.status_code == 200
    data = response.get_json()
    assert data["settings"] == {}


def test_put_device_persists(client):
    put_resp = client.put("/api/phase-settings/device", json={"settings": {"1.1": False}})
    assert put_resp.status_code == 200
    assert put_resp.get_json()["ok"] is True

    get_resp = client.get("/api/phase-settings/device")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["settings"]["1.1"] is False


def test_put_project_persists(client, project):
    pid = project["id"]
    put_resp = client.put(f"/api/projects/{pid}/phase-settings", json={"settings": {"1.1": False}})
    assert put_resp.status_code == 200
    assert put_resp.get_json()["ok"] is True

    get_resp = client.get(f"/api/projects/{pid}/phase-settings")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["settings"]["1.1"] is False


# ── Always-on rejection ───────────────────────────────────────────────────────

def test_put_device_rejects_always_on_disable(client):
    response = client.put("/api/phase-settings/device", json={"settings": {"0": False}})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_put_project_rejects_always_on_disable(client, project):
    pid = project["id"]
    response = client.put(f"/api/projects/{pid}/phase-settings", json={"settings": {"0": False}})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_put_device_accepts_always_on_enable(client):
    response = client.put("/api/phase-settings/device", json={"settings": {"0": True}})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# ── Not found ─────────────────────────────────────────────────────────────────

def test_get_project_unknown_returns_404(client):
    response = client.get("/api/projects/nonexistent-project-99/phase-settings")
    assert response.status_code == 404
    assert "error" in response.get_json()


# ── Listing ───────────────────────────────────────────────────────────────────

def test_get_phases_available_includes_core_phases(client):
    response = client.get("/api/phases/available")
    assert response.status_code == 200
    ids = {p["id"] for p in response.get_json()["phases"]}
    assert {"0", "1.0", "2.0", "4.2", "5.1", "5.2", "6"}.issubset(ids)


def test_get_phases_available_marks_always_on(client):
    response = client.get("/api/phases/available")
    phases_by_id = {p["id"]: p for p in response.get_json()["phases"]}
    for pid in ("0", "1.0", "2.0", "4.2", "6"):
        assert phases_by_id[pid]["always_on"] is True, f"phase {pid} should be always_on"


def test_get_phases_available_marks_user_gates(client):
    response = client.get("/api/phases/available")
    phases_by_id = {p["id"]: p for p in response.get_json()["phases"]}
    assert phases_by_id["1.4"]["is_user_gate"] is True
    assert phases_by_id["4.2"]["is_user_gate"] is True


def test_get_phases_available_sorted_by_phase_key(client):
    response = client.get("/api/phases/available")
    ids = [p["id"] for p in response.get_json()["phases"]]
    static_ids = [i for i in ids if not i.startswith("3.")]
    from core.phase import phase_key
    assert static_ids == sorted(static_ids, key=phase_key)


def test_get_phases_available_includes_execution_templates(client):
    """Execution template ids 3.x.0/1/3/4 must appear; 3.x.2 is hidden (implicit via 3.x.1)."""
    response = client.get("/api/phases/available")
    phases_by_id = {p["id"]: p for p in response.get_json()["phases"]}

    for pid in ("3.x.0", "3.x.1", "3.x.3", "3.x.4"):
        assert pid in phases_by_id, f"{pid} missing from /api/phases/available"
        assert phases_by_id[pid]["templated"] is True, f"{pid} should have templated=true"

    assert "3.x.2" not in phases_by_id, "3.x.2 should be hidden from /api/phases/available"

    assert phases_by_id["3.x.0"]["always_on"] is True
    assert phases_by_id["3.x.4"]["always_on"] is True
    assert phases_by_id["3.x.1"]["always_on"] is False
    assert phases_by_id["3.x.3"]["always_on"] is False


def test_get_phases_available_non_templated_phases_have_templated_false(client):
    response = client.get("/api/phases/available")
    phases_by_id = {p["id"]: p for p in response.get_json()["phases"]}

    for pid in ("0", "1.0", "2.0", "4.2", "6"):
        assert phases_by_id[pid]["templated"] is False, f"{pid} should have templated=false"


# ── Execution always-on enforcement ──────────────────────────────────────────

def test_put_project_rejects_3_1_0_disable(client, project):
    pid = project["id"]
    response = client.put(f"/api/projects/{pid}/phase-settings", json={"settings": {"3.1.0": False}})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_put_project_rejects_3_1_4_disable(client, project):
    pid = project["id"]
    response = client.put(f"/api/projects/{pid}/phase-settings", json={"settings": {"3.1.4": False}})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_put_project_allows_3_1_3_disable(client, project):
    """Commit approval gate (3.1.3) is now freely toggleable."""
    pid = project["id"]
    response = client.put(f"/api/projects/{pid}/phase-settings", json={"settings": {"3.1.3": False}})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# ── Input shape validation (issue #767) ──────────────────────────────────────

def test_put_device_invalid_settings_shape_returns_400(client):
    response = client.put("/api/phase-settings/device", json={"settings": "not a dict"})
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data
    assert "object" in data["error"]


def test_put_device_invalid_settings_key_returns_400(client):
    # JSON forces string keys, so we test nested invalid shapes (non-bool value
    # used as a proxy for a fuzz-invalid body where the value type is wrong).
    response = client.put("/api/phase-settings/device", json={"settings": {"1.1": {"nested": True}}})
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data
    assert "bool" in data["error"]


def test_put_device_invalid_settings_value_returns_400(client):
    response = client.put("/api/phase-settings/device", json={"settings": {"1.1": "yes"}})
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data
    assert "bool" in data["error"]
