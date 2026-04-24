"""Admin token authentication for the Flask admin panel.

Applies a ``before_request`` guard that requires ``Authorization: Bearer <token>``
(or ``?token=<token>``) on every protected route. Auth is always required —
when no admin token has been configured on this device, every non-whitelist
route returns 401 so the frontend can show the CLI instructions.

There is no runtime flag or environment variable that can disable this guard.
The pytest suite reaches protected routes through a fixture-based test client
wrapper that injects a real token; see ``backend/tests/conftest.py``.

The whitelist is kept intentionally small: static assets needed to render the
token-entry screen, the auth status/check endpoints, and WebSocket upgrades
(which authenticate differently via a query param because browsers cannot set
custom headers on the initial WS handshake).
"""
from flask import g, jsonify, request

from core.db import get_db
from core.device_settings import (
    get_admin_token_hash,
    verify_token,
)

UNPROTECTED_PREFIXES = (
    "/css/",
    "/js/",
    "/img/",
    "/i18n/",
)

UNPROTECTED_EXACT = frozenset({
    "/api/auth/check",
    "/api/auth/status",
    "/favicon.ico",
})

WEBSOCKET_PATH_PREFIXES = (
    "/ws/",
)


def _is_websocket_upgrade(req) -> bool:
    if req.headers.get("Upgrade", "").lower() == "websocket":
        return True
    return any(req.path.startswith(prefix) for prefix in WEBSOCKET_PATH_PREFIXES)


def _extract_bearer_token(req) -> str:
    header = req.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return (req.args.get("token") or "").strip()


def _should_bypass(path: str) -> bool:
    if path == "/" or path in UNPROTECTED_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in UNPROTECTED_PREFIXES)


def _auth_required_response(configured: bool):
    return jsonify({
        "error": "authentication_required",
        "reason": "Admin token required. Generate one via the CLI and paste it in the admin panel.",
        "configured": configured,
    }), 401


def register_auth_guard(app):
    """Install the global before_request auth guard on the Flask app."""

    @app.before_request
    def _auth_guard():
        g.admin_authenticated = False
        path = request.path

        if request.method == "OPTIONS":
            return None

        if _should_bypass(path):
            return None

        if _is_websocket_upgrade(request):
            # WebSocket handlers enforce auth themselves before accepting data
            # (see routes/terminal_routes.py, routes/lsp.py, routes/setup.py).
            # At the HTTP layer we let the upgrade handshake through so flask-sock
            # can negotiate; the socket is closed on the inside if the token is
            # missing/invalid.
            return None

        db = get_db()
        try:
            token = _extract_bearer_token(request)
            if token and verify_token(db, token):
                g.admin_authenticated = True
                return None

            configured = get_admin_token_hash(db) is not None
            return _auth_required_response(configured)
        finally:
            db.close()


def websocket_auth_ok(db, token: str) -> bool:
    """Check whether a websocket should be allowed based on a supplied token.

    The presented token must verify against the stored admin token hash.
    """
    return verify_token(db, token or "")
