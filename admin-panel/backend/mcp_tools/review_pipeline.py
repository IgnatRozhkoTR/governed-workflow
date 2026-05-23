"""MCP tools exposing the headless review pipeline status and blocking wait."""
import time
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import mcp, with_mcp_workspace, mcp_error
from services import review_pipeline_service

_TERMINAL_STATES = {"done", "failed"}
_POLL_INTERVAL_S = 2
_TIMEOUT_MIN_S = 30
_TIMEOUT_MAX_S = 3600


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


@mcp.tool(annotations=ToolAnnotations(
    title="Wait for review pipeline to finish",
    readOnlyHint=True,
    idempotentHint=False,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_wait_for_review(
    ws,
    project,
    db,
    locale,
    timeout_s: Annotated[int, Field(description=(
        "Maximum seconds to wait for the pipeline to reach a terminal state "
        "(done or failed). Bounded to [30, 3600]. Default 1800 (30 minutes)."
    ))] = 1800,
) -> dict:
    """Block until the phase 4.0 review pipeline reaches a terminal state.

    Purpose:
        Replace the orchestrator's poll-and-sleep loop at phase 4.0. The tool
        returns when the pipeline state is one of ``done`` or ``failed``, or
        when ``timeout_s`` seconds have elapsed (whichever comes first). The
        returned dict is the same shape as ``workspace_review_pipeline_summary``,
        with an additional ``timed_out`` boolean key set to True only when the
        timeout expired before a terminal state was observed.

    Parameters:
        timeout_s — Maximum seconds to wait. Bounded to [30, 3600]. Default
            1800 (30 minutes), which is well above typical pipeline runtime.

    Returns:
        Dict with the same keys as ``workspace_review_pipeline_summary``, plus
        ``timed_out: bool``.

    Errors:
        not_found — workspace not detected from cwd, or no pipeline run is
        tracked for this workspace.
    """
    clamped_timeout = max(_TIMEOUT_MIN_S, min(timeout_s, _TIMEOUT_MAX_S))
    workspace_id = ws["id"]

    # DB connection is held by the decorator but pipeline status is purely
    # in-memory, so no DB activity occurs during the wait loop.
    status = review_pipeline_service.get_status(workspace_id)
    if status is None:
        return mcp_error(
            "not_found",
            "no pipeline status for workspace",
            retryable=False,
            details={"workspace_id": workspace_id},
        )

    deadline = time.monotonic() + clamped_timeout
    while True:
        if status.state in _TERMINAL_STATES:
            return _summary_with_timed_out(workspace_id, timed_out=False)

        if time.monotonic() >= deadline:
            return _summary_with_timed_out(workspace_id, timed_out=True)

        time.sleep(_POLL_INTERVAL_S)
        current = review_pipeline_service.get_status(workspace_id)
        if current is None:
            return mcp_error(
                "not_found",
                "pipeline status lost during wait (server may have restarted)",
                retryable=False,
                details={"workspace_id": workspace_id},
            )
        status = current


def _summary_with_timed_out(workspace_id: int, timed_out: bool) -> dict:
    summary = review_pipeline_service.status_summary(workspace_id)
    if summary is None:
        return mcp_error(
            "not_found",
            "pipeline status lost after wait completed",
            retryable=False,
            details={"workspace_id": workspace_id},
        )
    summary["timed_out"] = timed_out
    return summary
