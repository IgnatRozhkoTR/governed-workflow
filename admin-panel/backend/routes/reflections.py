"""Reflection endpoints scoped to a workspace."""
from flask import Blueprint, jsonify, request

from core.db import get_db_ctx
from core.decorators import with_workspace
from core.i18n import t
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

_MESSAGE_BY_CODE = {
    "not_found": "api.error.reflection.notFound",
    "llm_unconfigured": "api.error.reflection.llmUnconfigured",
    "llm_failure": "api.error.reflection.llmFailure",
    "llm_invalid_json": "api.error.reflection.llmInvalidJson",
    "no_session_found": "api.error.reflection.noSessionFound",
}


def _error_response(exc: ReflectionServiceError, locale: str = "en"):
    status = _STATUS_BY_CODE.get(exc.code, 500)
    key = _MESSAGE_BY_CODE.get(exc.code)
    message = t(key, locale) if key else str(exc)
    return jsonify({"error": message}), status


@bp.route("/api/ws/<project_id>/<path:branch>/reflections", methods=["GET"])
@with_workspace
def list_reflections(db, ws, project):
    locale = ws["locale"] or "en"
    try:
        items = reflection_service.list_reflections(db, ws["id"])
    except ReflectionServiceError as exc:
        return _error_response(exc, locale)
    return jsonify(items)


@bp.route("/api/ws/<project_id>/<path:branch>/reflections", methods=["POST"])
@with_workspace
def run_reflection(db, ws, project):
    locale = ws["locale"] or "en"
    try:
        result = reflection_service.run(db, ws["id"])
    except ReflectionServiceError as exc:
        return _error_response(exc, locale)
    return jsonify(result), 201


@bp.route("/api/ws/<project_id>/<path:branch>/reflections/<int:rid>", methods=["GET"])
@with_workspace
def get_reflection(db, ws, project, rid: int):
    locale = ws["locale"] or "en"
    try:
        result = reflection_service.get(db, rid)
    except ReflectionServiceError as exc:
        return _error_response(exc, locale)
    return jsonify(result)
