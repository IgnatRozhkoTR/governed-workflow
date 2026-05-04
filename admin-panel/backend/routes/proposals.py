"""Global (workspace-agnostic) endpoints for approval-gated proposals."""
from flask import Blueprint, jsonify, request

from core.db import get_db_ctx
from services import proposal_service
from services.proposal_service import ProposalServiceError


bp = Blueprint("proposals", __name__)


_STATUS_BY_CODE = {
    "not_found": 404,
    "invalid_type": 400,
    "invalid_payload": 400,
    "invalid_state": 409,
    "execution_failed": 500,
}


def _error_response(exc: ProposalServiceError):
    status = _STATUS_BY_CODE.get(exc.code, 500)
    body = {"error": str(exc), "code": exc.code}
    if exc.details:
        body["details"] = exc.details
    return jsonify(body), status


def _parse_int_param(name: str) -> int | None:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@bp.route("/api/proposals", methods=["GET"])
def list_proposals_endpoint():
    status = request.args.get("status") or None
    type_ = request.args.get("type") or None
    origin = request.args.get("origin") or None
    project_id = _parse_int_param("project_id")
    workspace_id = _parse_int_param("workspace_id")
    with get_db_ctx() as db:
        try:
            items = proposal_service.list_proposals(
                db,
                status=status,
                type=type_,
                origin=origin,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        except ProposalServiceError as exc:
            return _error_response(exc)
    return jsonify(items)


@bp.route("/api/proposals/<int:proposal_id>", methods=["GET"])
def get_proposal_endpoint(proposal_id: int):
    with get_db_ctx() as db:
        try:
            item = proposal_service.get(db, proposal_id)
        except ProposalServiceError as exc:
            return _error_response(exc)
    return jsonify(item)


@bp.route("/api/proposals", methods=["POST"])
def create_proposal_endpoint():
    body = request.get_json(silent=True) or {}
    type_ = body.get("type", "")
    title = body.get("title", "")
    text = body.get("body", "")
    payload = body.get("payload") or {}
    origin = body.get("origin", "agent")
    workspace_id = body.get("workspace_id")
    project_id = body.get("project_id")
    with get_db_ctx() as db:
        try:
            item = proposal_service.create(
                db,
                type=type_,
                title=title,
                body=text,
                payload=payload,
                origin=origin,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        except ProposalServiceError as exc:
            return _error_response(exc)
    return jsonify(item), 201


@bp.route("/api/proposals/<int:proposal_id>/approve", methods=["POST"])
def approve_proposal_endpoint(proposal_id: int):
    with get_db_ctx() as db:
        try:
            item = proposal_service.approve(db, proposal_id)
        except ProposalServiceError as exc:
            return _error_response(exc)
    return jsonify(item)


@bp.route("/api/proposals/<int:proposal_id>/reject", methods=["POST"])
def reject_proposal_endpoint(proposal_id: int):
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "")
    with get_db_ctx() as db:
        try:
            item = proposal_service.reject(db, proposal_id, reason)
        except ProposalServiceError as exc:
            return _error_response(exc)
    return jsonify(item)


@bp.route("/api/proposals/<int:proposal_id>/resolve", methods=["POST"])
def resolve_proposal_endpoint(proposal_id: int):
    with get_db_ctx() as db:
        try:
            item = proposal_service.resolve(db, proposal_id)
        except ProposalServiceError as exc:
            return _error_response(exc)
    return jsonify(item)
