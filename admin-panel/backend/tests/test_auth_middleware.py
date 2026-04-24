"""Tests for the Flask before_request auth guard in ``core.auth``.

This suite exercises the REAL middleware, so the test-only env bypass is
explicitly removed for every test in the module. A single test at the bottom
re-enables the bypass to document the escape hatch used by the rest of the
pytest suite.
"""
import pytest

from core.db import get_db
from core.device_settings import (
    DISABLE_AUTH_ENV_VAR,
    clear_admin_token,
    generate_token,
    set_admin_token,
)


@pytest.fixture(autouse=True)
def _real_auth(monkeypatch):
    monkeypatch.delenv(DISABLE_AUTH_ENV_VAR, raising=False)


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


def test_protected_route_returns_401_when_no_token_configured(client):
    response = client.get("/api/projects")

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "authentication_required"
    assert body["configured"] is False


def test_protected_route_returns_401_when_no_token_presented(client, configured_token):
    response = client.get("/api/projects")

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "authentication_required"
    assert body["configured"] is True


def test_protected_route_returns_401_when_token_invalid(client, configured_token):
    response = client.get(
        "/api/projects",
        headers={"Authorization": "Bearer gwf_not_the_right_token"},
    )

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "authentication_required"
    assert body["configured"] is True


def test_protected_route_accessible_with_valid_bearer_token(client, configured_token):
    response = client.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {configured_token}"},
    )

    assert response.status_code == 200


def test_protected_route_accessible_with_valid_query_token(client, configured_token):
    response = client.get(f"/api/projects?token={configured_token}")

    assert response.status_code == 200


def test_auth_status_accessible_without_token_when_configured(client, configured_token):
    response = client.get("/api/auth/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["configured"] is True
    assert _is_setup_command(body.get("setup_command"))


def test_auth_status_returns_unconfigured_when_no_token_set(client):
    response = client.get("/api/auth/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["configured"] is False
    assert _is_setup_command(body.get("setup_command"))


def test_auth_status_setup_command_is_absolute_path(client):
    response = client.get("/api/auth/status")

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


def test_auth_check_validates_supplied_token(client, configured_token):
    response = client.post("/api/auth/check", json={"token": configured_token})

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["configured"] is True


def test_auth_check_rejects_wrong_token(client, configured_token):
    response = client.post("/api/auth/check", json={"token": "gwf_wrong"})

    assert response.status_code == 401
    body = response.get_json()
    assert body["ok"] is False
    assert body["configured"] is True


def test_auth_check_reports_no_token_configured(client):
    response = client.post("/api/auth/check", json={"token": ""})

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "no_token_configured"
    assert body["configured"] is False


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


def test_env_var_bypass_allows_all_protected_routes(client, monkeypatch):
    monkeypatch.setenv(DISABLE_AUTH_ENV_VAR, "1")

    response = client.get("/api/projects")

    assert response.status_code == 200
