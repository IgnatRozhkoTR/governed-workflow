"""HTTP endpoint for the headless review pipeline status snapshot."""
from flask import Blueprint, jsonify

from services import review_pipeline_service

bp = Blueprint("review_pipeline", __name__)


@bp.route(
    "/api/workspaces/<int:workspace_id>/review-pipeline-status",
    methods=["GET"],
)
def get_review_pipeline_status(workspace_id: int):
    """Return the current in-memory pipeline status for a workspace.

    Returns 404 when no pipeline has run yet for the given workspace
    (status registry is in-memory and cleared on server restart).
    """
    snapshot = review_pipeline_service.status_as_dict(workspace_id)
    if snapshot is None:
        return jsonify({"error": "no pipeline status for workspace"}), 404
    return jsonify(snapshot)
