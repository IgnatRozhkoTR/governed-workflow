"""HTTP endpoints for the reflection service."""
import asyncio
import dataclasses
import threading
from pathlib import Path

from flask import Blueprint, jsonify

from core.db import get_db_ctx
from core.decorators import with_workspace
from services import reflection_service
from services.reflection_service import ReflectionServiceError

reflection_bp = Blueprint("reflection", __name__)

_ERROR_STATUS_MAP = {
    "workspace_not_found": 404,
    "already_running": 409,
}

_ERROR_MESSAGE_MAP = {
    "workspace_not_found": "workspace not found",
    "already_running": "reflection already running",
}


def _handle_reflection_error(exc: ReflectionServiceError):
    status = _ERROR_STATUS_MAP.get(exc.code, 500)
    message = _ERROR_MESSAGE_MAP.get(exc.code, str(exc))
    return jsonify({"error": message}), status


def _run_reflection_thread(workspace_id: int, project_path: Path) -> None:
    asyncio.run(reflection_service.run_reflection(get_db_ctx, workspace_id, project_path))


@reflection_bp.route("/api/ws/<project_id>/<path:branch>/reflection/run", methods=["POST"])
@with_workspace
def run_reflection(db, ws, project):
    workspace_id = ws["id"]

    if reflection_service.get_status(workspace_id).state == "running":
        return jsonify({"error": "reflection already running"}), 409

    project_path = Path(project["path"])

    thread = threading.Thread(
        target=_run_reflection_thread,
        args=(workspace_id, project_path),
        name=f"reflection-ws-{workspace_id}",
        daemon=True,
    )
    thread.start()

    return jsonify({"state": "running", "workspace_id": workspace_id}), 202


@reflection_bp.route("/api/ws/<project_id>/<path:branch>/reflection/status", methods=["GET"])
@with_workspace
def get_status(db, ws, project):
    workspace_id = ws["id"]

    status = dataclasses.asdict(reflection_service.get_status(workspace_id))
    proposals = reflection_service.list_proposals_for_workspace(db, workspace_id)

    return jsonify({**status, "proposals": proposals})


@reflection_bp.route("/api/ws/<project_id>/<path:branch>/reflection/proposals", methods=["GET"])
@with_workspace
def get_proposals(db, ws, project):
    workspace_id = ws["id"]

    proposals = reflection_service.list_proposals_for_workspace(db, workspace_id)
    return jsonify(proposals)
