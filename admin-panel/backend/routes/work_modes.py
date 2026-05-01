"""HTTP endpoints for managing work modes (named phase-set presets) and workspace assignment."""
from flask import Blueprint, jsonify, request

from core.db import get_db_ctx
from services import work_mode_service
from services.work_mode_service import WorkModeServiceError


bp = Blueprint("work_modes", __name__)


_STATUS_BY_CODE = {
    "not_found": 404,
    "name_collision": 409,
    "invalid_phases": 400,
    "invalid_name": 400,
    "system_immutable": 409,
}


def _error_response(exc: WorkModeServiceError):
    status = _STATUS_BY_CODE.get(exc.code, 500)
    body = {"error": str(exc), "code": exc.code}
    if exc.details:
        body["details"] = exc.details
    return jsonify(body), status


@bp.route("/api/work-modes", methods=["GET"])
def list_modes_endpoint():
    with get_db_ctx() as db:
        try:
            modes = work_mode_service.list_modes(db)
        except WorkModeServiceError as exc:
            return _error_response(exc)
    return jsonify(modes)


@bp.route("/api/work-modes", methods=["POST"])
def create_mode_endpoint():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    description = body.get("description") or ""
    phases = body.get("phases") or []
    with get_db_ctx() as db:
        try:
            mode = work_mode_service.create(db, name=name, description=description, phases=phases)
        except WorkModeServiceError as exc:
            return _error_response(exc)
    return jsonify(mode), 201


@bp.route("/api/work-modes/<int:mode_id>", methods=["GET"])
def get_mode_endpoint(mode_id: int):
    with get_db_ctx() as db:
        try:
            mode = work_mode_service.get(db, mode_id)
        except WorkModeServiceError as exc:
            return _error_response(exc)
    return jsonify(mode)


@bp.route("/api/work-modes/<int:mode_id>", methods=["PATCH"])
def update_mode_endpoint(mode_id: int):
    body = request.get_json(silent=True) or {}
    name = body.get("name", None)
    description = body.get("description", None)
    phases = body.get("phases", None)
    with get_db_ctx() as db:
        try:
            mode = work_mode_service.update(
                db,
                mode_id,
                name=name,
                description=description,
                phases=phases,
            )
        except WorkModeServiceError as exc:
            return _error_response(exc)
    return jsonify(mode)


@bp.route("/api/work-modes/<int:mode_id>", methods=["DELETE"])
def delete_mode_endpoint(mode_id: int):
    with get_db_ctx() as db:
        try:
            work_mode_service.delete(db, mode_id)
        except WorkModeServiceError as exc:
            return _error_response(exc)
    return jsonify({"status": "deleted", "id": mode_id})


@bp.route("/api/workspaces/<int:workspace_id>/work-mode", methods=["PUT"])
def assign_mode_endpoint(workspace_id: int):
    body = request.get_json(silent=True) or {}
    mode_id = body.get("mode_id")
    if mode_id is None:
        return jsonify({"error": "mode_id is required", "code": "invalid_phases"}), 400
    try:
        mode_id_int = int(mode_id)
    except (TypeError, ValueError):
        return jsonify({"error": "mode_id must be an integer", "code": "invalid_phases"}), 400
    with get_db_ctx() as db:
        try:
            result = work_mode_service.assign(db, workspace_id, mode_id_int)
        except WorkModeServiceError as exc:
            return _error_response(exc)
    return jsonify(result)


@bp.route("/api/workspaces/<int:workspace_id>/work-mode/apply", methods=["POST"])
def apply_mode_endpoint(workspace_id: int):
    with get_db_ctx() as db:
        try:
            result = work_mode_service.apply(db, workspace_id)
        except WorkModeServiceError as exc:
            return _error_response(exc)
    return jsonify(result)
