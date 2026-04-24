#!/usr/bin/env python3
"""Workspace Control -- Flask backend for admin panel."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, jsonify
from advance.phases import register_module_phases_from_disk
from core.auth import register_auth_guard
from core.db import get_db_ctx, init_db
from core.device_settings import (
    clear_admin_token,
    generate_token,
    get_bind_host,
    set_admin_token,
)
from core.paths import DEFAULT_TOOLS_DIR
from routes import register_blueprints

os.environ.setdefault("GOVERNED_WORKFLOW_TOOLS_DIR", str(DEFAULT_TOOLS_DIR))


def create_app():
    templates_dir = Path(__file__).resolve().parent.parent / "frontend"
    app = Flask(__name__, static_folder=None, template_folder=str(templates_dir))
    register_module_phases_from_disk()
    register_blueprints(app)
    register_auth_guard(app)

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        return jsonify({"error": str(e)}), 500

    return app


def _run_auth_token_command() -> int:
    init_db()
    with get_db_ctx() as db:
        token = generate_token()
        set_admin_token(db, token)
        db.commit()
    print(token)
    print("Paste this token in the admin panel when prompted. It will not be shown again.")
    return 0


def _run_auth_reset_command() -> int:
    init_db()
    with get_db_ctx() as db:
        clear_admin_token(db)
        db.commit()
    print("Auth disabled. Run `auth-token` to generate a new token.")
    return 0


def _maybe_dispatch_cli() -> bool:
    if len(sys.argv) < 2:
        return False
    command = sys.argv[1]
    if command == "auth-token":
        sys.exit(_run_auth_token_command())
    if command == "auth-reset":
        sys.exit(_run_auth_reset_command())
    return False


if __name__ == "__main__":
    _maybe_dispatch_cli()
    Path(__file__).resolve().parent.mkdir(parents=True, exist_ok=True)
    init_db()
    with get_db_ctx() as db:
        bind_host = get_bind_host(db)
    app = create_app()
    print("Workspace Control server starting...")
    print(f"  URL: http://localhost:5111")
    print(f"  Bind host: {bind_host}")
    app.run(host=bind_host, port=5111, debug=False)
