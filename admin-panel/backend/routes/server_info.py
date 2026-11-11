"""Host identity route used by clients to build ssh-remote URIs."""
import getpass
import socket
import sys
from pathlib import Path

from flask import Blueprint, jsonify

bp = Blueprint("server_info", __name__)


@bp.route("/api/server-info", methods=["GET"])
def get_server_info():
    return jsonify({
        "ok": True,
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "home": str(Path.home()),
        "platform": sys.platform,
    })
