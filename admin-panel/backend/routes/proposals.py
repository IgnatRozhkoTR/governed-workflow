"""Proposal list and resolve routes."""
from flask import Blueprint, jsonify, request

from services import proposal_service
from core.decorators import with_workspace

bp = Blueprint("proposals", __name__)

_RESOLVE_ERROR_STATUS = {
    "proposal_not_found": 404,
    "already_resolved": 409,
    "invalid_argument": 400,
}


@bp.route("/api/ws/<project_id>/<path:branch>/proposals", methods=["GET"])
@with_workspace
def list_proposals(db, ws, project):
    status = request.args.get("status") or None
    implementation_kind = request.args.get("implementation_kind") or None

    try:
        proposals = proposal_service.list_proposals(
            db,
            workspace_id=ws["id"],
            implementation_kind=implementation_kind,
            status=status,
        )
    except proposal_service.ProposalServiceError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"proposals": proposals})


@bp.route(
    "/api/ws/<project_id>/<path:branch>/proposals/<int:proposal_id>/resolve",
    methods=["PUT"],
)
@with_workspace
def resolve_proposal(db, ws, project, proposal_id):
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    result_json = body.get("result_json")

    try:
        updated = proposal_service.resolve_proposal(
            db, proposal_id, status=status, result_json=result_json
        )
    except proposal_service.ProposalServiceError as e:
        status_code = _RESOLVE_ERROR_STATUS.get(e.code, 400)
        return jsonify({"error": str(e)}), status_code

    db.commit()
    return jsonify(updated)
