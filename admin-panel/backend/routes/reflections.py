"""Reflection endpoints scoped to a workspace."""
from flask import Blueprint, jsonify, request

from core.db import get_db_ctx
from core.decorators import with_workspace
from services import reflection_service
from services.reflection_service import ReflectionServiceError

bp = Blueprint("reflections", __name__)

_STATUS_BY_CODE = {
    "not_found": 404,
    "llm_unconfigured": 503,
    "llm_failure": 502,
    "llm_invalid_json": 502,
    "no_session_found": 409,
}


def _error_response(exc: ReflectionServiceError):
    status = _STATUS_BY_CODE.get(exc.code, 500)
    return jsonify({"error": str(exc)}), status


@bp.route("/api/ws/<project_id>/<path:branch>/reflections", methods=["GET"])
@with_workspace
def list_reflections(db, ws, project):
    try:
        items = reflection_service.list_reflections(db, ws["id"])
    except ReflectionServiceError as exc:
        return _error_response(exc)
    return jsonify(items)


@bp.route("/api/ws/<project_id>/<path:branch>/reflections", methods=["POST"])
@with_workspace
def run_reflection(db, ws, project):
    try:
        result = reflection_service.run(db, ws["id"])
    except ReflectionServiceError as exc:
        return _error_response(exc)
    return jsonify(result), 201


@bp.route("/api/ws/<project_id>/<path:branch>/reflections/<int:rid>", methods=["GET"])
@with_workspace
def get_reflection(db, ws, project, rid: int):
    try:
        result = reflection_service.get(db, rid)
    except ReflectionServiceError as exc:
        return _error_response(exc)
    return jsonify(result)
