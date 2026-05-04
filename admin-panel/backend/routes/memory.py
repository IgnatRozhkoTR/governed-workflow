"""Memory endpoints scoped to a workspace."""
from flask import Blueprint, jsonify, request

from core.decorators import with_workspace
from services import memory_service
from services.memory_provider import MemoryProviderError

bp = Blueprint("memory", __name__)

_STATUS_BY_CODE = {
    "memory_not_found": 404,
    "invalid_scope": 400,
    "invalid_input": 400,
    "provider_unavailable": 503,
    "transient": 503,
}


def _error_response(exc: MemoryProviderError):
    status = _STATUS_BY_CODE.get(exc.code, 500)
    body = {"error": str(exc)}
    if exc.code == "provider_unavailable":
        body["hint"] = "enable the mempalace module via the Setup page"
    return jsonify(body), status


@bp.route("/api/ws/<project_id>/<path:branch>/memory", methods=["GET"])
@with_workspace
def list_memories(db, ws, project):
    raw = request.args.getlist("scope_filter")
    scope_filter = None
    if raw:
        import json
        try:
            scope_filter = [json.loads(s) for s in raw]
        except (ValueError, TypeError) as exc:
            return jsonify({"error": f"Invalid scope_filter: {exc}"}), 400
    try:
        items = memory_service.list_memories(scope_filter)
    except MemoryProviderError as exc:
        return _error_response(exc)
    return jsonify(items)


@bp.route("/api/ws/<project_id>/<path:branch>/memory/<memory_id>", methods=["GET"])
@with_workspace
def get_memory(db, ws, project, memory_id: str):
    try:
        result = memory_service.get(memory_id)
    except MemoryProviderError as exc:
        return _error_response(exc)
    return jsonify(result)


@bp.route("/api/ws/<project_id>/<path:branch>/memory", methods=["POST"])
@with_workspace
def save_memory(db, ws, project):
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    scope = body.get("scope", {})
    metadata = body.get("metadata", {})
    try:
        result = memory_service.save(content, scope, metadata)
    except MemoryProviderError as exc:
        return _error_response(exc)
    return jsonify(result), 201


@bp.route("/api/ws/<project_id>/<path:branch>/memory/<memory_id>", methods=["DELETE"])
@with_workspace
def delete_memory(db, ws, project, memory_id: str):
    try:
        memory_service.delete(memory_id)
    except MemoryProviderError as exc:
        return _error_response(exc)
    return jsonify({"ok": True, "deleted_id": memory_id})


@bp.route("/api/ws/<project_id>/<path:branch>/memory/search", methods=["POST"])
@with_workspace
def search_memories(db, ws, project):
    body = request.get_json(silent=True) or {}
    query = body.get("query", "")
    scope_filter = body.get("scope_filter")
    limit = body.get("limit", 10)
    try:
        results = memory_service.retrieve(query, scope_filter, limit)
    except MemoryProviderError as exc:
        return _error_response(exc)
    return jsonify(results)
