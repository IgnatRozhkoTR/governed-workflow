"""Tests for GET /api/server-info."""
import getpass
import socket
import sys
from pathlib import Path

from core.db import get_db
from core.device_settings import clear_admin_token


def test_server_info_returns_host_identity(client):
    response = client.get("/api/server-info")

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "home": str(Path.home()),
        "platform": sys.platform,
    }


def test_server_info_requires_token(raw_client):
    response = raw_client.get("/api/server-info")

    assert response.status_code == 401


def test_server_info_rejects_unconfigured_token(raw_client):
    db = get_db()
    try:
        clear_admin_token(db)
        db.commit()
    finally:
        db.close()

    assert raw_client.get("/api/server-info").status_code == 401
