"""Tests for terminal WebSocket routes: by-name attach and route ordering."""
import json

import pytest

import routes.terminal_routes as terminal_routes_module


class _FakeWs:
    """Records frames sent by the handler under test."""

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)


@pytest.fixture(autouse=True)
def no_real_run_pty(monkeypatch):
    """Guard against any accidental real PTY/tmux spawn in this module."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("run_pty_websocket must be mocked in these tests")
    monkeypatch.setattr(terminal_routes_module, "run_pty_websocket", _forbidden)


def _request_ctx(app, name, token=""):
    return app.test_request_context(f"/ws/terminal-session/{name}?token={token}")


def test_by_name_unauthenticated_sends_error_and_does_not_attach(app, monkeypatch):
    monkeypatch.setattr(terminal_routes_module, "websocket_auth_ok", lambda db, token: False)
    called = []
    monkeypatch.setattr(terminal_routes_module, "run_pty_websocket", lambda ws, name: called.append(name))

    ws = _FakeWs()
    with _request_ctx(app, "my-session", token="bad-token"):
        terminal_routes_module._attach_terminal_ws_by_name(ws, "my-session")

    assert called == []
    assert len(ws.sent) == 1
    assert json.loads(ws.sent[0]) == {"error": "authentication_required"}


def test_by_name_unknown_session_sends_error_and_does_not_attach(app, monkeypatch):
    monkeypatch.setattr(terminal_routes_module, "websocket_auth_ok", lambda db, token: True)
    monkeypatch.setattr(
        terminal_routes_module, "list_sessions",
        lambda: [{"name": "ws-other-session", "attached": False}],
    )
    called = []
    monkeypatch.setattr(terminal_routes_module, "run_pty_websocket", lambda ws, name: called.append(name))

    ws = _FakeWs()
    with _request_ctx(app, "ws-missing-session", token="good-token"):
        terminal_routes_module._attach_terminal_ws_by_name(ws, "ws-missing-session")

    assert called == []
    assert len(ws.sent) == 1
    assert json.loads(ws.sent[0])["error"] == "No tmux session. Use Start or Resume first."


def test_by_name_known_session_attaches_exactly_once(app, monkeypatch):
    monkeypatch.setattr(terminal_routes_module, "websocket_auth_ok", lambda db, token: True)
    monkeypatch.setattr(
        terminal_routes_module, "list_sessions",
        lambda: [{"name": "ws-real-session", "attached": False}],
    )
    called = []
    monkeypatch.setattr(terminal_routes_module, "run_pty_websocket", lambda ws, name: called.append(name))

    ws = _FakeWs()
    with _request_ctx(app, "ws-real-session", token="good-token"):
        terminal_routes_module._attach_terminal_ws_by_name(ws, "ws-real-session")

    assert called == ["ws-real-session"]
    assert ws.sent == []


@pytest.mark.parametrize("candidate_name", [
    "ws-real-sessio",       # prefix of a real session name
    "ws-real-session-x",    # suffix-extended, looks like a real session name
    "ws-real-session; rm -rf /",  # shell metacharacters
    "../ws-real-session",   # path traversal style
])
def test_by_name_rejects_lookalike_and_unsafe_names(app, monkeypatch, candidate_name):
    monkeypatch.setattr(terminal_routes_module, "websocket_auth_ok", lambda db, token: True)
    monkeypatch.setattr(
        terminal_routes_module, "list_sessions",
        lambda: [{"name": "ws-real-session", "attached": False}],
    )
    called = []
    monkeypatch.setattr(terminal_routes_module, "run_pty_websocket", lambda ws, name: called.append(name))

    ws = _FakeWs()
    with app.test_request_context(
        "/ws/terminal-session/x", query_string={"token": "good-token"}
    ):
        terminal_routes_module._attach_terminal_ws_by_name(ws, candidate_name)

    assert called == []
    assert len(ws.sent) == 1
    assert json.loads(ws.sent[0])["error"] == "No tmux session. Use Start or Resume first."


def test_workspace_ws_route_still_resolves_to_its_own_handler(app):
    adapter = app.url_map.bind("localhost", url_scheme="ws")

    endpoint, args = adapter.match(
        "/ws/terminal/my-project/my-branch", method="GET", websocket=True
    )
    assert endpoint == "terminal_ws"
    assert args == {"project": "my-project", "branch": "my-branch"}

    endpoint, args = adapter.match(
        "/ws/terminal/my-project/my-branch/claude", method="GET", websocket=True
    )
    assert endpoint == "terminal_ws_kind"
    assert args == {"project": "my-project", "branch": "my-branch", "session_kind": "claude"}

    endpoint, args = adapter.match(
        "/ws/terminal-session/ws-real-session", method="GET", websocket=True
    )
    assert endpoint == "terminal_ws_by_name"
    assert args == {"name": "ws-real-session"}


def test_project_named_session_still_reaches_its_own_workspace_terminal(app):
    """A project whose id is literally 'session' must not collide with the
    by-name terminal route, which now lives under /ws/terminal-session/."""
    adapter = app.url_map.bind("localhost", url_scheme="ws")

    endpoint, args = adapter.match(
        "/ws/terminal/session/some-branch", method="GET", websocket=True
    )
    assert endpoint == "terminal_ws"
    assert args == {"project": "session", "branch": "some-branch"}
