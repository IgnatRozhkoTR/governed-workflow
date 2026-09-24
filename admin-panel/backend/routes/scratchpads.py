"""Scratchpad read/list/write routes.

Scratchpads are markdown reports rendered and editable in the admin panel UI.
This is a narrow, purpose-built surface scoped only to
``.claude/scratchpad/`` — unlike files.py's general file browser, writes here
are restricted to a flat set of ``.md`` files with validated names. Directory
resolution, name validation, and file I/O live in services/scratchpad_service.py,
shared with the scratchpad MCP tools.
"""
import logging

from flask import Blueprint, jsonify, request

from core.decorators import with_workspace
from services import scratchpad_service

logger = logging.getLogger(__name__)

bp = Blueprint("scratchpads", __name__)


@bp.route("/api/ws/<project_id>/<path:branch>/scratchpads", methods=["GET"])
@with_workspace
def list_scratchpads(db, ws, project):
    repo = request.args.get("repo", "").strip()
    scratchpad_dir, err = scratchpad_service.resolve_scratchpad_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    return jsonify({"files": scratchpad_service.list_scratchpads(scratchpad_dir)})


@bp.route("/api/ws/<project_id>/<path:branch>/scratchpads/content", methods=["GET"])
@with_workspace
def read_scratchpad(db, ws, project):
    repo = request.args.get("repo", "").strip()
    name = request.args.get("name", "").strip()

    name_err = scratchpad_service.validate_name(name)
    if name_err:
        return jsonify({"error": name_err}), 400

    scratchpad_dir, err = scratchpad_service.resolve_scratchpad_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    try:
        return jsonify(scratchpad_service.read_scratchpad(scratchpad_dir, name))
    except scratchpad_service.ScratchpadServiceError:
        return jsonify({"error": "scratchpad_not_found"}), 404


@bp.route("/api/ws/<project_id>/<path:branch>/scratchpads/content", methods=["PUT"])
@with_workspace
def write_scratchpad(db, ws, project):
    repo = request.args.get("repo", "").strip()
    name = request.args.get("name", "").strip()

    name_err = scratchpad_service.validate_name(name)
    if name_err:
        return jsonify({"error": name_err}), 400

    scratchpad_dir, err = scratchpad_service.resolve_scratchpad_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    body = request.json or {}
    content = body.get("content", "")

    result = scratchpad_service.write_scratchpad(scratchpad_dir, name, content)
    return jsonify({"ok": True, "name": result["name"], "updated_at": result["updated_at"]})
