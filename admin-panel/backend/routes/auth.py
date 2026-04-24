"""Auth + network-mode routes.

These endpoints have to stay callable *without* a token in some cases — the
frontend needs to know whether auth is configured before it can show the token
paste screen, and check a pasted token before persisting it to localStorage.
``/api/auth/check`` and ``/api/auth/status`` are therefore on the auth bypass
list; all other routes below require a valid token like any other admin route.
"""
import logging
import os
import socket
import threading
from typing import Iterable

from flask import Blueprint, jsonify, request

from core.db import get_db_ctx
from core.device_settings import (
    DEFAULT_BIND_HOST,
    NETWORK_BIND_HOST,
    get_bind_host,
    is_auth_enabled,
    set_bind_host,
    verify_token,
)

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
    """Return whether auth is enabled on this device. Unauthenticated."""
    with get_db_ctx() as db:
        return jsonify({
            "auth_enabled": is_auth_enabled(db),
        })


@bp.route("/api/auth/check", methods=["POST"])
def auth_check():
    """Verify a token. Used by the paste-token screen. Unauthenticated by route,
    but validates the supplied token before returning ok."""
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    with get_db_ctx() as db:
        if not is_auth_enabled(db):
            return jsonify({"ok": True, "auth_enabled": False})
        ok = verify_token(db, token)
        if not ok:
            return jsonify({"ok": False}), 401
        return jsonify({"ok": True, "auth_enabled": True})


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
