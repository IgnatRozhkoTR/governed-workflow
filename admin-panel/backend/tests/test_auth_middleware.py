"""Tests for the Flask before_request auth guard in ``core.auth``."""
import pytest

from core.db import get_db
from core.device_settings import clear_admin_token, generate_token, set_admin_token


@pytest.fixture
def configured_token():
    """Configure an admin token for the duration of the test."""
    token = generate_token()
    db = get_db()
    try:
        set_admin_token(db, token)
        db.commit()
        yield token
    finally:
        clear_admin_token(db)
        db.commit()
        db.close()


def test_all_routes_accessible_when_auth_disabled(client, project):
    """With no token configured, the guard lets every request through."""
    response = client.get(f"/api/projects")

    assert response.status_code == 200


def test_protected_route_returns_401_when_no_token_presented(client, configured_token):
    response = client.get("/api/projects")

    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_required"


def test_protected_route_returns_401_when_token_invalid(client, configured_token):
    response = client.get(
        "/api/projects",
        headers={"Authorization": "Bearer gwf_not_the_right_token"},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_token"


def test_protected_route_accessible_with_valid_bearer_token(client, configured_token):
    response = client.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {configured_token}"},
    )

    assert response.status_code == 200


def test_protected_route_accessible_with_valid_query_token(client, configured_token):
    response = client.get(f"/api/projects?token={configured_token}")

    assert response.status_code == 200


def test_auth_status_always_accessible_without_token(client, configured_token):
    response = client.get("/api/auth/status")

    assert response.status_code == 200
    assert response.get_json() == {"auth_enabled": True}


def test_auth_status_returns_false_when_no_token_configured(client):
    response = client.get("/api/auth/status")

    assert response.status_code == 200
    assert response.get_json() == {"auth_enabled": False}


def test_auth_check_validates_supplied_token(client, configured_token):
    response = client.post("/api/auth/check", json={"token": configured_token})

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["auth_enabled"] is True


def test_auth_check_rejects_wrong_token(client, configured_token):
    response = client.post("/api/auth/check", json={"token": "gwf_wrong"})

    assert response.status_code == 401
    assert response.get_json()["ok"] is False


def test_auth_check_ok_when_auth_disabled(client):
    response = client.post("/api/auth/check", json={"token": ""})

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["auth_enabled"] is False


def test_static_css_path_bypasses_auth(client, configured_token):
    response = client.get("/css/app.css")

    assert response.status_code != 401


def test_static_js_path_bypasses_auth(client, configured_token):
    response = client.get("/js/app.js")

    assert response.status_code != 401


def test_static_i18n_path_bypasses_auth(client, configured_token):
    response = client.get("/i18n/en.json")

    assert response.status_code != 401


def test_index_path_bypasses_auth(client, configured_token):
    response = client.get("/")

    assert response.status_code != 401


def test_websocket_upgrade_bypasses_auth_at_http_layer(client, configured_token):
    """The HTTP layer must not 401 a websocket upgrade — the WS handler enforces
    auth itself because browsers cannot attach custom headers to the handshake."""
    response = client.get(
        "/ws/terminal/foo/bar",
        headers={
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": "x" * 16,
            "Sec-WebSocket-Version": "13",
        },
    )

    assert response.status_code != 401
