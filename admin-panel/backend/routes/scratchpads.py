"""Scratchpad read/list/write routes.

Scratchpads are markdown reports an agent writes with its normal file tools
into a fixed ``.claude/scratchpad/`` directory (see workspaces.py's
``_ensure_scratchpad_dir``), rendered and editable in the admin panel UI.
This is a narrow, purpose-built surface scoped only to that directory —
unlike files.py's general file browser, writes here are restricted to a flat
set of ``.md`` files with validated names.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from core.decorators import with_workspace
from routes.files import _resolve_repo_dir

logger = logging.getLogger(__name__)

bp = Blueprint("scratchpads", __name__)


def _scratchpad_dir(db, ws, project, repo_param):
    """Resolve the ``.claude/scratchpad/`` directory for this request.

    Single-repo projects always use the workspace's own working_dir — unlike
    the general file-browser routes, scratchpads do not scope into nested
    inner repos there. Multi-repo projects use the workspace's composite
    working_dir (the parent directory shared by all attached repos) when
    ``repo`` is omitted/".", or defer to files.py's attached-repo resolution
    (and its ``repo_required``/``repo_not_found`` error codes) otherwise.
    """
    if project["project_type"] != "multi" or not repo_param or repo_param == ".":
        return Path(ws["working_dir"]) / ".claude" / "scratchpad", None

    working_dir, err = _resolve_repo_dir(db, ws, project, repo_param)
    if err:
        return None, err
    return Path(working_dir) / ".claude" / "scratchpad", None


def _validate_name(name):
    if not name:
        return "invalid_name"
    if not name.endswith(".md"):
        return "invalid_name"
    if "/" in name or ".." in name or Path(name).is_absolute():
        return "invalid_name"
    return None


def _iso_mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _title_for(path):
    try:
        with path.open() as f:
            first_line = f.readline().strip()
    except OSError:
        first_line = ""
    if first_line.startswith("# "):
        return first_line[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


@bp.route("/api/ws/<project_id>/<path:branch>/scratchpads", methods=["GET"])
@with_workspace
def list_scratchpads(db, ws, project):
    repo = request.args.get("repo", "").strip()
    scratchpad_dir, err = _scratchpad_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    if not scratchpad_dir.is_dir():
        return jsonify({"files": []})

    files = []
    for entry in scratchpad_dir.iterdir():
        if not entry.is_file() or entry.suffix != ".md":
            continue
        files.append({
            "name": entry.name,
            "title": _title_for(entry),
            "updated_at": _iso_mtime(entry),
            "size": entry.stat().st_size,
        })

    files.sort(key=lambda f: f["updated_at"], reverse=True)
    return jsonify({"files": files})


@bp.route("/api/ws/<project_id>/<path:branch>/scratchpads/content", methods=["GET"])
@with_workspace
def read_scratchpad(db, ws, project):
    repo = request.args.get("repo", "").strip()
    name = request.args.get("name", "").strip()

    name_err = _validate_name(name)
    if name_err:
        return jsonify({"error": name_err}), 400

    scratchpad_dir, err = _scratchpad_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    file_path = scratchpad_dir / name
    if not file_path.is_file():
        return jsonify({"error": "scratchpad_not_found"}), 404

    return jsonify({
        "content": file_path.read_text(),
        "name": name,
        "updated_at": _iso_mtime(file_path),
    })


@bp.route("/api/ws/<project_id>/<path:branch>/scratchpads/content", methods=["PUT"])
@with_workspace
def write_scratchpad(db, ws, project):
    repo = request.args.get("repo", "").strip()
    name = request.args.get("name", "").strip()

    name_err = _validate_name(name)
    if name_err:
        return jsonify({"error": name_err}), 400

    scratchpad_dir, err = _scratchpad_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    body = request.json or {}
    content = body.get("content", "")

    scratchpad_dir.mkdir(parents=True, exist_ok=True)
    file_path = scratchpad_dir / name
    file_path.write_text(content)

    return jsonify({
        "ok": True,
        "name": name,
        "updated_at": _iso_mtime(file_path),
    })
