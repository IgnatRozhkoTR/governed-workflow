from typing import Annotated

from pydantic import Field
from mcp.types import ToolAnnotations

from mcp_tools import mcp, with_mcp_workspace, mcp_error
from services import pr_service, repo_service


def _match_repo(repos, repo):
    return next((r for r in repos if r["rel_path"] == repo or r["name"] == repo), None)


def _valid_repo_names(repos):
    return sorted({r["rel_path"] for r in repos} | {r["name"] for r in repos})


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    idempotentHint=False,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_attach_repo(
    ws, project, db, locale,
    repo: Annotated[str, Field(description="The rel_path or name of a registered, enabled repo to attach to this workspace.")],
) -> dict:
    """Attach a registered repo to this multi-repo workspace, creating its worktree.

    Purpose:
        Multi-repo workspaces start with no repos attached. Call this once per
        repo the ticket touches before editing files under that repo's path.

    Parameters:
        repo: The rel_path or name of a registered, enabled repo.

    Returns:
        {"repo_id", "rel_path", "name", "branch", "worktree_path", "base_sync",
        "instruction"} on success.

    Errors:
        business — this is not a multi-repo project, the repo is disabled,
            the workspace is not active, or the repo is already attached.
        not_found — no enabled repo matches the given name.

    Example:
        workspace_attach_repo(repo="service-a")
    """
    if project["project_type"] != "multi":
        return mcp_error(
            "business",
            "workspace_attach_repo is only available for multi-repo projects",
            retryable=False,
        )

    enabled_repos = [r for r in repo_service.list_repos(db, project["id"]) if r["enabled"]]
    match = _match_repo(enabled_repos, repo)
    if match is None:
        valid = _valid_repo_names(enabled_repos)
        return mcp_error(
            "not_found",
            f"No enabled repo matches {repo!r}. Valid names: {valid}",
            retryable=False,
            details={"valid_repos": valid},
        )

    repo_row = repo_service.get_repo(db, project["id"], match["id"])
    try:
        result = repo_service.attach_repo(db, ws, project, repo_row)
    except repo_service.RepoServiceError as exc:
        return mcp_error("business", str(exc), retryable=False, details={"code": exc.code})

    result["instruction"] = (
        f"Repo '{result['rel_path']}' is now attached at {result['worktree_path']} "
        f"on branch {result['branch']}."
    )
    return result


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_save_pr(
    ws, project, db, locale,
    url: Annotated[str, Field(description="The pull/merge request URL.")],
    repo: Annotated[str, Field(description="Multi-repo projects only: rel_path or name of the repo this PR belongs to. Leave empty to auto-resolve when exactly one repo is attached. Must stay empty for single-repo projects.")] = "",
    title: Annotated[str, Field(description="Optional PR title.")] = "",
) -> dict:
    """Save (or update) the pull/merge request URL for this workspace.

    Purpose:
        Records where the ticket's PR/MR lives so the panel and other tools
        can surface it. Upserts — calling again with the same repo replaces
        the previous URL/title.

    Parameters:
        url: The PR/MR URL, must start with http:// or https://.
        repo: For multi-repo projects, the repo the PR belongs to (rel_path
            or name). Required when more than one repo is attached.
        title: Optional short title for the PR.

    Returns:
        The saved PR row: {id, workspace_id, repo_id, url, title, created,
        rel_path, name}.

    Errors:
        validation — url is malformed, or repo was given for a single-repo project.
        not_found — repo does not match any registered repo.
        business — repo was omitted while zero or multiple repos are attached.

    Example:
        workspace_save_pr(url="https://github.com/org/repo/pull/42", repo="service-a")
    """
    repo = repo.strip()
    resolved_title = title.strip() or None

    if project["project_type"] != "multi":
        if repo:
            return mcp_error(
                "validation", "repo must be empty for single-repo projects", retryable=False
            )
        repo_id = None
    else:
        if repo:
            registered = repo_service.list_repos(db, project["id"])
            match = _match_repo(registered, repo)
            if match is None:
                valid = _valid_repo_names(registered)
                return mcp_error(
                    "not_found",
                    f"No registered repo matches {repo!r}. Valid names: {valid}",
                    retryable=False,
                    details={"valid_repos": valid},
                )
            repo_id = match["id"]
        else:
            attached_rows = db.execute(
                "SELECT wr.repo_id, pr.rel_path FROM workspace_repos wr "
                "JOIN project_repos pr ON pr.id = wr.repo_id WHERE wr.workspace_id = ?",
                (ws["id"],),
            ).fetchall()
            if len(attached_rows) == 1:
                repo_id = attached_rows[0]["repo_id"]
            else:
                names = sorted(row["rel_path"] for row in attached_rows)
                return mcp_error(
                    "business",
                    f"repo is required: {len(attached_rows)} repos attached. Attached: {names}",
                    retryable=False,
                    details={"attached_repos": names},
                )

    try:
        result = pr_service.save_pr(db, ws["id"], url, repo_id=repo_id, title=resolved_title)
    except pr_service.PrServiceError as exc:
        return mcp_error("validation", str(exc), retryable=False)

    return result
