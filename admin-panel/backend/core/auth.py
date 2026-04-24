"""Admin token authentication for the Flask admin panel.

Applies a ``before_request`` guard that requires ``Authorization: Bearer <token>``
for protected routes once an admin token has been configured. The whitelist is
kept intentionally small: static assets needed to render the token-entry screen,
the auth status/check endpoints, and WebSocket upgrades (which authenticate
differently via a query param because browsers cannot set custom headers on the
initial WS handshake).
"""
from flask import g, jsonify, request

from core.db import get_db
from core.device_settings import is_auth_enabled, verify_token

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


def _auth_required_response():
    return jsonify({
        "error": "authentication_required",
        "reason": "Admin token required. Paste your token in the admin panel.",
    }), 401


def _auth_invalid_response():
    return jsonify({
        "error": "invalid_token",
        "reason": "Admin token invalid. Re-paste the token from your terminal.",
    }), 401


def register_auth_guard(app):
    """Install the global before_request auth guard on the Flask app."""

    @app.before_request
    def _auth_guard():
        g.admin_authenticated = False
        path = request.path

        if request.method == "OPTIONS":
            return None

        if _is_websocket_upgrade(request):
            # WebSocket handlers enforce auth themselves before accepting data
            # (see routes/terminal_routes.py, routes/lsp.py, routes/setup.py).
            # At the HTTP layer we let the upgrade handshake through so flask-sock
            # can negotiate; the socket is closed on the inside if the token is
            # missing/invalid.
            return None

        if _should_bypass(path):
            return None

        db = get_db()
        try:
            if not is_auth_enabled(db):
                g.admin_authenticated = True
                return None

            token = _extract_bearer_token(request)
            if not token:
                return _auth_required_response()

            if not verify_token(db, token):
                return _auth_invalid_response()

            g.admin_authenticated = True
            return None
        finally:
            db.close()


def websocket_auth_ok(db, token: str) -> bool:
    """Check whether a websocket should be allowed based on a supplied token.

    Auth is considered ok when either auth is disabled (no token configured)
    or the supplied token verifies against the configured hash.
    """
    if not is_auth_enabled(db):
        return True
    return verify_token(db, token or "")
