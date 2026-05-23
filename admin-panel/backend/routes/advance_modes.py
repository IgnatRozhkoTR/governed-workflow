"""HTTP endpoints for per-project advance-mode configuration."""
import logging

from flask import Blueprint, jsonify, request

from core.decorators import with_project
from services.advance_mode_service import (
    AdvanceModeServiceError,
    VALID_MODES,
    list_modes,
    set_modes,
)

log = logging.getLogger(__name__)

bp = Blueprint("advance_modes", __name__)

_STATUS_BY_CODE = {
    "invalid_key": 400,
    "invalid_mode": 400,
}


def _error_response(exc: AdvanceModeServiceError):
    status = _STATUS_BY_CODE.get(exc.code, 500)
    body = {"error": str(exc), "code": exc.code}
    if exc.details:
        body["details"] = exc.details
    return jsonify(body), status


def _validate_modes_payload(raw_modes) -> tuple[dict[str, str] | None, str | None]:
    """Coerce and validate the modes dict from the request body.

    Returns ``(modes_dict, None)`` on success, or ``(None, error_message)``
    on invalid input. Keys are boundary_key strings; values are mode strings.
    """
    if not isinstance(raw_modes, dict):
        return None, "modes must be a JSON object"
    coerced: dict[str, str] = {}
    for key, value in raw_modes.items():
        if not isinstance(key, str) or not key.strip():
            return None, f"modes key {key!r} must be a non-empty string"
        if not isinstance(value, str) or value not in VALID_MODES:
            return None, f"modes[{key!r}] must be one of {sorted(VALID_MODES)}, got {value!r}"
        coerced[key] = value
    return coerced, None


@bp.route("/api/projects/<project_id>/advance-modes", methods=["GET"])
@with_project
def get_advance_modes(db, project):
    modes = list_modes(db, project["id"])
    return jsonify(modes)


@bp.route("/api/projects/<project_id>/advance-modes", methods=["PUT"])
@with_project
def put_advance_modes(db, project):
    body = request.get_json(silent=True) or {}
    raw_modes = body.get("modes")
    if raw_modes is None:
        return jsonify({"error": "request body must include 'modes'", "code": "invalid_payload"}), 400

    modes, err = _validate_modes_payload(raw_modes)
    if err:
        return jsonify({"error": err, "code": "invalid_payload"}), 400

    try:
        set_modes(db, project["id"], modes)
    except AdvanceModeServiceError as exc:
        return _error_response(exc)

    updated = list_modes(db, project["id"])
    return jsonify(updated)
