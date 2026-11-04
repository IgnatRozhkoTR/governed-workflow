#!/usr/bin/env python3
"""Workspace Control -- Flask backend for admin panel."""
import os
import subprocess
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
    get_admin_token_hash,
    get_bind_host,
    set_admin_token,
)
from core.paths import DEFAULT_TOOLS_DIR, admin_token_setup_command
from routes import register_blueprints

os.environ.setdefault("GOVERNED_WORKFLOW_TOOLS_DIR", str(DEFAULT_TOOLS_DIR))


def create_app():
    templates_dir = Path(__file__).resolve().parent.parent / "frontend"
    app = Flask(__name__, static_folder=None, template_folder=str(templates_dir))
    app.config['TEMPLATES_AUTO_RELOAD'] = True
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


def _copy_to_clipboard(text: str) -> bool:
    """Push ``text`` onto the OS clipboard using the first available native tool.

    Returns True on success, False on any failure (tool missing, pipe error,
    non-zero exit). Failures are swallowed so the CLI can degrade gracefully
    when no clipboard integration is available (e.g. headless Linux without
    xclip/xsel/wl-copy). The raw token stays printed to stdout either way.
    """
    if sys.platform == "darwin":
        candidates: list[list[str]] = [["pbcopy"]]
        use_shell = False
    elif sys.platform.startswith("linux"):
        candidates = [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
        use_shell = False
    elif sys.platform.startswith("win"):
        candidates = [["clip"]]
        use_shell = True
    else:
        return False

    for cmd in candidates:
        try:
            result = subprocess.run(
                cmd if not use_shell else " ".join(cmd),
                input=text,
                text=True,
                shell=use_shell,
                check=False,
                capture_output=True,
            )
        except (FileNotFoundError, OSError):
            continue
        if result.returncode == 0:
            return True
    return False


def _run_auth_token_command() -> int:
    init_db()
    force = "--force" in sys.argv[2:]
    setup_command = admin_token_setup_command()
    reset_command = setup_command.rsplit(" ", 1)[0] + " auth-reset"

    with get_db_ctx() as db:
        existing_hash = get_admin_token_hash(db)
        if existing_hash is not None and not force:
            print(
                "An admin token is already configured on this device. "
                "Re-running `auth-token` will invalidate the existing token and "
                "disconnect any open admin-panel browser sessions.\n\n"
                "To rotate the token anyway, run:\n"
                f"  {setup_command} --force\n\n"
                "Or to clear the existing token first:\n"
                f"  {reset_command}",
                file=sys.stderr,
            )
            return 1
        token = generate_token()
        set_admin_token(db, token)
        db.commit()

    print(token)
    if _copy_to_clipboard(token):
        print(
            "Admin token generated. Copied to system clipboard — "
            "paste it into the admin panel login screen."
        )
    else:
        print(
            "Admin token generated. Copy the token above and paste it into "
            "the admin panel login screen."
        )
    return 0


def _run_auth_reset_command() -> int:
    init_db()
    with get_db_ctx() as db:
        clear_admin_token(db)
        db.commit()
    print(f"Auth disabled. Run `{admin_token_setup_command()}` to generate a new token.")
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


def _rerender_all_projects_on_startup():
    """Re-render every project's payload so on-disk config matches current phase classes.

    Run only from the __main__ entry point — create_app() stays free of this so
    pytest never triggers filesystem writes when it imports the app factory.
    """
    from services.configurator_service import rerender_all_projects

    with get_db_ctx() as db:
        rerender_all_projects(db)


if __name__ == "__main__":
    _maybe_dispatch_cli()
    Path(__file__).resolve().parent.mkdir(parents=True, exist_ok=True)
    init_db()
    with get_db_ctx() as db:
        bind_host = get_bind_host(db)
        token_configured = get_admin_token_hash(db) is not None
    app = create_app()
    _rerender_all_projects_on_startup()
    print("Workspace Control server starting...")
    print(f"  URL: http://localhost:5111")
    print(f"  Bind host: {bind_host}")
    if not token_configured:
        print(f"  [!] No admin token configured. Run `{admin_token_setup_command()}` to generate one.")
    app.run(host=bind_host, port=5111, debug=False, threaded=True)
