"""MCP tool exposing the headless review pipeline completion summary."""
from mcp.types import ToolAnnotations

from mcp_tools import mcp, with_mcp_workspace, mcp_error
from services import review_pipeline_service


@mcp.tool(annotations=ToolAnnotations(
    title="Review pipeline summary",
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_review_pipeline_summary(ws, project, db, locale) -> dict:
    """Return a flat completion summary for the phase 4.0 review pipeline.

    Purpose:
        Lets the orchestrator gate ``workspace_advance`` at phase 4.0. Confirm
        ``is_complete`` is True and ``is_ok`` is True before advancing. When
        ``files_failed > 0`` or ``integration_failed > 0``, decide whether to
        re-trigger the pipeline (Run Review button on the workspace page, or
        ``POST /api/workspaces/<id>/review-pipeline/start``) or to proceed with
        the partial result if the failures are recoverable.

    Parameters:
        No parameters. Workspace is auto-detected from the working directory.

    Returns:
        Dict with keys: workspace_id, state, files_total, files_done,
        files_failed, files_in_progress, files_with_findings, files_clean,
        failed_files, integration_done, integration_failed, integration_total,
        is_complete, is_ok, error, started_at, finished_at.

    Errors:
        not_found — workspace not detected from cwd, or no pipeline run is
        tracked for this workspace (in-memory registry, cleared on server
        restart; trigger a run via the Run Review button or
        ``POST /api/workspaces/<id>/review-pipeline/start``).
    """
    summary = review_pipeline_service.status_summary(ws["id"])
    if summary is None:
        return mcp_error(
            "not_found",
            "no pipeline status for workspace",
            retryable=False,
            details={"workspace_id": ws["id"]},
        )
    return summary
