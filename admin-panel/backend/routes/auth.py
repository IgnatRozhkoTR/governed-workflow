"""Auth + network-mode routes.

``/api/auth/status`` and ``/api/auth/check`` stay callable without a token so
the frontend can render the login screen and verify a pasted token before
persisting it to localStorage. Every other route below is behind the global
before_request auth guard.
"""
import logging
import os
import socket
import threading

from flask import Blueprint, jsonify, request

from core.db import get_db_ctx
from core.device_settings import (
    DEFAULT_BIND_HOST,
    NETWORK_BIND_HOST,
    get_admin_token_hash,
    get_bind_host,
    set_bind_host,
    verify_token,
)
from core.paths import admin_token_setup_command

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)


def _lan_ip_candidates() -> list[str]:
    """Return a best-effort list of LAN-reachable IP addresses for this host.

    The admin panel uses these to help the user reach the server from another
    device after switching to network mode — binding to ``0.0.0.0`` is not a
    valid browser destination on its own.
    """
    candidates: set[str] = set()

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ip and not ip.startswith(("127.", "::1")) and ip != "0.0.0.0":
                candidates.add(ip)
    except socket.gaierror:
        pass

    # Trick used widely: connect a UDP socket to a public address to learn
    # which local interface would be used. Nothing is actually sent.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("1.1.1.1", 80))
            candidates.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass

    return sorted(candidates)


@bp.route("/api/auth/status", methods=["GET"])
def auth_status():
    """Return whether an admin token has been configured. Unauthenticated.

    Used by the login screen to pick between "no token yet — generate one"
    and "paste your existing token" subtitles. Also returns the absolute
    ``auth-token`` command so the UI renders a copy-paste-ready invocation
    that works from any working directory.
    """
    with get_db_ctx() as db:
        configured = get_admin_token_hash(db) is not None
    return jsonify({
        "configured": configured,
        "setup_command": admin_token_setup_command(),
    })


@bp.route("/api/auth/check", methods=["POST"])
def auth_check():
    """Verify a token. Used by the paste-token screen. Unauthenticated by route,
    but validates the supplied token before returning ok."""
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    with get_db_ctx() as db:
        stored_hash = get_admin_token_hash(db)
        if stored_hash is None:
            return jsonify({
                "error": "no_token_configured",
                "configured": False,
            }), 401
        if verify_token(db, token):
            return jsonify({"ok": True, "configured": True})
        return jsonify({"ok": False, "configured": True}), 401


@bp.route("/api/network-mode", methods=["GET"])
def get_network_mode():
    """Return current bind host + LAN IP hints for the UI toggle."""
    with get_db_ctx() as db:
        current = get_bind_host(db)
    return jsonify({
        "bind_host": current,
        "network_enabled": current == NETWORK_BIND_HOST,
        "default_host": DEFAULT_BIND_HOST,
        "network_host": NETWORK_BIND_HOST,
        "lan_ips": _lan_ip_candidates(),
    })


@bp.route("/api/network-mode", methods=["PUT"])
def set_network_mode():
    """Persist a new bind host. Caller must follow up with /api/restart."""
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled"))
    host = NETWORK_BIND_HOST if enabled else DEFAULT_BIND_HOST
    with get_db_ctx() as db:
        set_bind_host(db, host)
        db.commit()
    return jsonify({
        "bind_host": host,
        "network_enabled": enabled,
        "restart_required": True,
    })


def _restart_process():
    """Replace the current process with a fresh invocation of the same
    command line, preserving the Python interpreter so an active venv keeps
    being used. Tmux sessions live in a separate daemon so they are untouched
    by execv."""
    logger.info("Restarting admin panel via execv")
    python = os.sys.executable
    args = [python] + os.sys.argv
    os.execv(python, args)


@bp.route("/api/restart", methods=["POST"])
def restart():
    """Schedule a backend restart after responding to the caller.

    The frontend calls this after flipping the network-mode toggle so that the
    new ``bind_host`` takes effect. Tmux sessions and the SQLite DB survive
    because they live outside the Python process.
    """
    timer = threading.Timer(0.5, _restart_process)
    timer.daemon = True
    timer.start()
    return jsonify({"ok": True, "status": "restart_scheduled"})
