"""Tests for the Flask before_request auth guard in ``core.auth``.

Every test here uses ``raw_client`` so the real middleware runs — the wrapped
``client`` fixture auto-injects a valid bearer token and would mask the 401
paths we need to verify.
"""
import pytest

from core.db import get_db
from core.device_settings import clear_admin_token


@pytest.fixture
def no_admin_token():
    """Clear the session-wide admin token hash so protected routes 401.

    ``clean_db`` re-installs the token after the test, so subsequent tests
    using the wrapped client keep working.
    """
    db = get_db()
    try:
        clear_admin_token(db)
        db.commit()
    finally:
        db.close()


def test_protected_route_returns_401_when_no_token_configured(raw_client, no_admin_token):
    response = raw_client.get("/api/projects")

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "authentication_required"
    assert body["configured"] is False


def test_protected_route_returns_401_when_no_token_presented(raw_client, admin_token):
    response = raw_client.get("/api/projects")

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "authentication_required"
    assert body["configured"] is True


def test_protected_route_returns_401_when_token_invalid(raw_client, admin_token):
    response = raw_client.get(
        "/api/projects",
        headers={"Authorization": "Bearer gwf_not_the_right_token"},
    )

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "authentication_required"
    assert body["configured"] is True


def test_protected_route_accessible_with_valid_bearer_token(raw_client, admin_token):
    response = raw_client.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200


def test_protected_route_accessible_with_valid_query_token(raw_client, admin_token):
    response = raw_client.get(f"/api/projects?token={admin_token}")

    assert response.status_code == 200


def test_auth_status_accessible_without_token_when_configured(raw_client, admin_token):
    response = raw_client.get("/api/auth/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["configured"] is True
    assert _is_setup_command(body.get("setup_command"))


def test_auth_status_returns_unconfigured_when_no_token_set(raw_client, no_admin_token):
    response = raw_client.get("/api/auth/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["configured"] is False
    assert _is_setup_command(body.get("setup_command"))


def test_auth_status_setup_command_is_absolute_path(raw_client):
    response = raw_client.get("/api/auth/status")

    body = response.get_json()
    cmd = body["setup_command"]
    assert cmd.startswith("python3 /")
    assert cmd.endswith("admin-panel/backend/app.py auth-token")


def _is_setup_command(value) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("python3 /")
        and value.endswith("admin-panel/backend/app.py auth-token")
    )


def test_auth_check_validates_supplied_token(raw_client, admin_token):
    response = raw_client.post("/api/auth/check", json={"token": admin_token})

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["configured"] is True


def test_hook_check_permission_accessible_without_token(raw_client, admin_token):
    """The pre-tool hook runs inside an agent session and has no bearer token,
    so /api/hook/check-permission must remain callable unauthenticated."""
    response = raw_client.post(
        "/api/hook/check-permission",
        json={"cwd": "/tmp", "tool_name": "Read"},
    )
    assert response.status_code == 200


def test_hook_session_start_accessible_without_token(raw_client, admin_token):
    """The session-start hook fires at agent boot with no token available."""
    response = raw_client.post(
        "/api/hook/session-start",
        json={"session_id": "sess-1", "cwd": "/tmp"},
    )
    assert response.status_code == 200


def test_auth_check_rejects_wrong_token(raw_client, admin_token):
    response = raw_client.post("/api/auth/check", json={"token": "gwf_wrong"})

    assert response.status_code == 401
    body = response.get_json()
    assert body["ok"] is False
    assert body["configured"] is True


def test_auth_check_reports_no_token_configured(raw_client, no_admin_token):
    response = raw_client.post("/api/auth/check", json={"token": ""})

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "no_token_configured"
    assert body["configured"] is False


def test_static_css_path_bypasses_auth(raw_client):
    response = raw_client.get("/css/app.css")

    assert response.status_code != 401


def test_static_js_path_bypasses_auth(raw_client):
    response = raw_client.get("/js/app.js")

    assert response.status_code != 401


def test_static_i18n_path_bypasses_auth(raw_client):
    response = raw_client.get("/i18n/en.json")

    assert response.status_code != 401


def test_static_img_path_bypasses_auth(raw_client):
    response = raw_client.get("/img/logo.png")

    assert response.status_code != 401


def test_index_path_bypasses_auth(raw_client):
    response = raw_client.get("/")

    assert response.status_code != 401


def test_websocket_upgrade_bypasses_auth_at_http_layer(raw_client):
    """The HTTP layer must not 401 a websocket upgrade — the WS handler enforces
    auth itself because browsers cannot attach custom headers to the handshake."""
    response = raw_client.get(
        "/ws/terminal/foo/bar",
        headers={
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": "x" * 16,
            "Sec-WebSocket-Version": "13",
        },
    )

    assert response.status_code != 401
