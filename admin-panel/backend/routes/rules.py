"""Rule management endpoints (project .claude/rules/*.md files)."""
from flask import Blueprint, jsonify, request

from core.decorators import with_project
from services import rule_service
from services.rule_service import RuleServiceError


bp = Blueprint("rules", __name__)


_STATUS_BY_CODE = {
    "not_found": 404,
    "already_exists": 409,
    "default_immutable": 403,
    "invalid_name": 400,
    "invalid_frontmatter": 400,
}


def _error_response(exc: RuleServiceError):
    status = _STATUS_BY_CODE.get(exc.code, 500)
    return jsonify({"error": str(exc), "code": exc.code}), status


@bp.route("/api/projects/<project_id>/rules", methods=["GET"])
@with_project
def list_rules_endpoint(db, project):
    rules = rule_service.list_rules(project["path"])
    return jsonify(rules)


@bp.route("/api/projects/<project_id>/rules/<name>", methods=["GET"])
@with_project
def get_rule_endpoint(db, project, name):
    try:
        rule = rule_service.get_rule(project["path"], name)
    except RuleServiceError as exc:
        return _error_response(exc)
    return jsonify(rule)


@bp.route("/api/projects/<project_id>/rules", methods=["POST"])
@with_project
def create_rule_endpoint(db, project):
    body = request.json or {}
    name = body.get("name", "")
    description = body.get("description", "")
    paths = body.get("paths", [])
    content = body.get("body", "")
    try:
        rule = rule_service.create_rule(project["path"], name, description, paths, content)
    except RuleServiceError as exc:
        return _error_response(exc)
    return jsonify(rule), 201


@bp.route("/api/projects/<project_id>/rules/<name>", methods=["PUT"])
@with_project
def update_rule_endpoint(db, project, name):
    body = request.json or {}
    description = body.get("description", None)
    paths = body.get("paths", None)
    content = body.get("body", None)
    try:
        rule = rule_service.update_rule(
            project["path"], name,
            description=description, paths=paths, body=content,
        )
    except RuleServiceError as exc:
        return _error_response(exc)
    return jsonify(rule)


@bp.route("/api/projects/<project_id>/rules/<name>", methods=["DELETE"])
@with_project
def delete_rule_endpoint(db, project, name):
    try:
        rule_service.delete_rule(project["path"], name)
    except RuleServiceError as exc:
        return _error_response(exc)
    return jsonify({"status": "deleted", "name": name})
