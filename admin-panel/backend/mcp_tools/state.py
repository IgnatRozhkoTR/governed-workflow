import json

from mcp.types import ToolAnnotations

from mcp_tools import mcp, with_mcp_workspace
from core.db import ws_field
from core.i18n import t
from services import discussion_service
from services import plan_service
from services import pr_service
from services import progress_service
from services import repo_service
from services import research_service
from services.phase_sequencer import resolve_phase_sequence


def _multi_repo_state(db, ws, project):
    """Build the {attached, available} repo view for a multi-repo workspace."""
    attached_rows = db.execute(
        "SELECT wr.repo_id, pr.rel_path, pr.name, wr.branch, wr.worktree_path, pr.base_branch "
        "FROM workspace_repos wr JOIN project_repos pr ON pr.id = wr.repo_id "
        "WHERE wr.workspace_id = ? ORDER BY pr.rel_path",
        (ws["id"],),
    ).fetchall()
    attached_ids = {row["repo_id"] for row in attached_rows}

    attached = []
    for row in attached_rows:
        repo_row = repo_service.get_repo(db, project["id"], row["repo_id"])
        attached.append({
            "rel_path": row["rel_path"],
            "name": row["name"],
            "branch": row["branch"],
            "worktree_path": row["worktree_path"],
            "base_branch": row["base_branch"],
            "git_rules": repo_service.resolve_git_rules(db, project, repo_row),
        })

    available = [
        {"rel_path": r["rel_path"], "name": r["name"], "base_branch": r["base_branch"]}
        for r in repo_service.list_repos(db, project["id"])
        if r["enabled"] and r["id"] not in attached_ids
    ]

    return {"attached": attached, "available": available}


@mcp.tool(annotations=ToolAnnotations(
    title="Get workspace state",
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_get_state(ws, project, db, locale) -> dict:
    """Return a compact overview of the current workspace state.

    Purpose:
        Single call to get phase, scope, context, open discussions, and
        summary counts for all major sections. Prefer this as the first
        call in any orchestrator turn; use the dedicated tools listed below
        only when full detail is needed.

    Parameters:
        No parameters. Workspace is auto-detected from the working directory.

    Returns:
        Dict with keys: phase, status, workflow_mode, review_mode, scope,
        phase_sequence, context, discussions, plan_summary, progress_summary,
        research_summary, unresolved_comments_count, review_issues_summary,
        criteria_summary, previous_sessions_count, locale, branch,
        working_dir, _detail_tools.

        `phase_sequence` is already filtered to the phases enabled for this
        workspace. When `workflow_mode` is `fast`, the optional research and
        review phases (1.3, 1.4, 4.0 and the 3.N.1/3.N.2/3.N.3 execution
        sub-phases) are intentionally absent, and `review_mode` is inert
        because the 4.0 review pipeline never runs.

    Errors:
        not_found  — no workspace matched the current working directory.

    Detail tools for full payloads:
        workspace_get_plan, workspace_get_progress,
        workspace_list_research / workspace_get_research,
        workspace_get_comments, workspace_get_review_issues,
        workspace_get_criteria."""
    scope = plan_service.get_scope(ws)
    plan = plan_service.get_plan(ws)
    _, phase_sequence = resolve_phase_sequence(db, ws, plan)

    context = {
        "ticket_id": ws["ticket_id"] or "",
        "ticket_name": ws["ticket_name"] or "",
        "context": ws["context_text"] or "",
        "file_references": json.loads(ws["context_refs_json"] or "[]"),
        "commit_message": ws_field(ws, "commit_message") or "",
    }

    execution = plan.get("execution", [])

    current_subphase = None
    if ws["phase"].startswith("3.") and "." in ws["phase"][2:]:
        sub_id = ws["phase"].rsplit(".", 1)[0]
        current_subphase = next((item for item in execution if item.get("id") == sub_id), None)

    plan_summary = {
        "description": plan.get("description", ""),
        "execution_count": len(execution),
        "execution_names": [{"id": item["id"], "name": item["name"]} for item in execution],
    }
    if current_subphase:
        plan_summary["current_subphase"] = current_subphase

    progress_summary = progress_service.get_progress_map(db, ws["id"])

    research_entries = research_service.list_research(db, ws["id"])
    research_summary = [{"id": e["id"], "topic": e["topic"], "proven": e["proven"]} for e in research_entries]

    comment_count = db.execute(
        "SELECT COUNT(*) as cnt FROM discussions WHERE workspace_id = ? AND scope IS NOT NULL AND status = 'open'",
        (ws["id"],)
    ).fetchone()["cnt"]

    review_rows = db.execute(
        "SELECT resolution, COUNT(*) as cnt FROM discussions "
        "WHERE workspace_id = ? AND scope = 'review' AND parent_id IS NULL GROUP BY resolution",
        (ws["id"],)
    ).fetchall()
    review_issues_summary = {row["resolution"]: row["cnt"] for row in review_rows}

    criteria_rows = db.execute(
        "SELECT status, COUNT(*) as cnt FROM acceptance_criteria WHERE workspace_id = ? GROUP BY status",
        (ws["id"],)
    ).fetchall()
    criteria_summary = {row["status"]: row["cnt"] for row in criteria_rows}

    session_count = db.execute(
        "SELECT COUNT(*) as cnt FROM session_history WHERE workspace_id = ?",
        (ws["id"],)
    ).fetchone()["cnt"]

    discussions = discussion_service.list_discussions(db, ws["id"], open_only=True)

    project_type = project["project_type"]

    result = {
        "phase": ws["phase"],
        "status": ws["status"],
        "workflow_mode": ws_field(ws, "workflow_mode", "standard"),
        "review_mode": ws_field(ws, "review_mode", "files_integration"),
        "scope": scope,
        "phase_sequence": phase_sequence,
        "context": context,
        "discussions": discussions,
        "plan_summary": plan_summary,
        "progress_summary": progress_summary,
        "research_summary": research_summary,
        "unresolved_comments_count": comment_count,
        "review_issues_summary": review_issues_summary,
        "criteria_summary": criteria_summary,
        "previous_sessions_count": session_count,
        "locale": ws["locale"],
        "branch": ws["branch"],
        "working_dir": ws["working_dir"],
        "project_type": project_type,
        "_detail_tools": {
            "plan": t("mcp.tool.getState.detail.plan", locale),
            "progress": t("mcp.tool.getState.detail.progress", locale),
            "research": t("mcp.tool.getState.detail.research", locale),
            "comments": t("mcp.tool.getState.detail.comments", locale),
            "review_issues": t("mcp.tool.getState.detail.reviewIssues", locale),
            "criteria": t("mcp.tool.getState.detail.criteria", locale),
        },
    }

    if project_type == "multi":
        result["repos"] = _multi_repo_state(db, ws, project)

    prs = pr_service.list_prs(db, ws["id"])
    if project_type == "multi" or prs:
        result["pull_requests"] = prs

    return result
