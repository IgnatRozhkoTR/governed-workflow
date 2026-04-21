"""Phase settings routes: device, project, and workspace level enablement."""
from flask import Blueprint, jsonify, request

from core.db import get_db, get_db_ctx
from core.decorators import with_project, with_workspace
from core.phase import phase_key
from services.phase_settings import get_scope_settings, is_always_on, set_scope_settings

bp = Blueprint("phase_settings", __name__)

_SETTINGS_BODY_ERRORS = {
    "not_dict": "settings must be a JSON object",
    "non_string_key": "settings keys must be strings (phase IDs)",
    "non_bool_value": "settings values must be booleans",
}


def _validate_settings_body(body: dict) -> tuple[dict | None, str | None]:
    """Validate that *body* contains a well-formed ``settings`` mapping.

    Returns ``(settings_dict, None)`` on success, or ``(None, error_message)``
    when the shape is invalid.
    """
    settings = body.get("settings", {})
    if not isinstance(settings, dict):
        return None, _SETTINGS_BODY_ERRORS["not_dict"]
    for key, value in settings.items():
        if not isinstance(key, str):
            return None, _SETTINGS_BODY_ERRORS["non_string_key"]
        if not isinstance(value, bool):
            return None, _SETTINGS_BODY_ERRORS["non_bool_value"]
    return settings, None


def _build_phases_list():
    from advance.phases import PHASE_REGISTRY
    phases = []
    for phase_id, phase in PHASE_REGISTRY.items():
        phases.append({
            "id": phase_id,
            "name": phase.name,
            "always_on": is_always_on(phase_id),
            "is_user_gate": phase.is_user_gate,
        })
    phases.sort(key=lambda p: phase_key(p["id"]))
    return phases


@bp.route("/api/phase-settings/device", methods=["GET"])
def get_device_settings():
    with get_db_ctx() as db:
        settings = get_scope_settings(db, "device", "")
    return jsonify({"settings": settings})


@bp.route("/api/phase-settings/device", methods=["PUT"])
def set_device_settings():
    body = request.get_json(silent=True) or {}
    settings, err = _validate_settings_body(body)
    if err:
        return jsonify({"error": err}), 400
    try:
        with get_db_ctx() as db:
            set_scope_settings(db, "device", "", settings)
            db.commit()
            updated = get_scope_settings(db, "device", "")
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify({"ok": True, "settings": updated})


@bp.route("/api/projects/<project_id>/phase-settings", methods=["GET"])
@with_project
def get_project_settings(db, project):
    settings = get_scope_settings(db, "project", str(project["id"]))
    return jsonify({"settings": settings})


@bp.route("/api/projects/<project_id>/phase-settings", methods=["PUT"])
@with_project
def set_project_settings(db, project):
    body = request.get_json(silent=True) or {}
    settings, err = _validate_settings_body(body)
    if err:
        return jsonify({"error": err}), 400
    try:
        set_scope_settings(db, "project", str(project["id"]), settings)
        db.commit()
        updated = get_scope_settings(db, "project", str(project["id"]))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify({"ok": True, "settings": updated})


@bp.route("/api/ws/<project_id>/<path:branch>/phase-settings", methods=["GET"])
@with_workspace
def get_workspace_settings(db, ws, project):
    settings = get_scope_settings(db, "workspace", str(ws["id"]))
    return jsonify({"settings": settings})


@bp.route("/api/ws/<project_id>/<path:branch>/phase-settings", methods=["PUT"])
@with_workspace
def set_workspace_settings(db, ws, project):
    body = request.get_json(silent=True) or {}
    settings, err = _validate_settings_body(body)
    if err:
        return jsonify({"error": err}), 400
    try:
        set_scope_settings(db, "workspace", str(ws["id"]), settings)
        db.commit()
        updated = get_scope_settings(db, "workspace", str(ws["id"]))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify({"ok": True, "settings": updated})


@bp.route("/api/phases/available", methods=["GET"])
def get_available_phases():
    return jsonify({"phases": _build_phases_list()})
