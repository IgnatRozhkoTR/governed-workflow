from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from mcp.types import ToolAnnotations

from mcp_tools import mcp, with_mcp_workspace, mcp_error
from core.i18n import t
from services import comment_service


@mcp.tool(annotations=ToolAnnotations(
    title="Get Comments",
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_get_comments(
    ws, project, db, locale,
    scope: Annotated[str, Field(description=(
        "Filter by scope — 'review' for blind-review findings, 'comment' for user comments. "
        "Empty string returns all."
    ))] = "",
    unresolved_only: Annotated[bool, Field(description=(
        "If True, omit comments whose status is 'resolved'."
    ))] = True,
) -> list:
    """Get workspace comments, optionally filtered by scope and resolution state.

    Purpose:
        Returns review findings or user comments attached to this workspace.
        Pass scope='review' to see code-review issues; scope='comment' for
        human comments posted via the admin panel. Use workspace_get_review_issues
        for the richer review-item structure.

    Parameters:
        scope: 'review', 'comment', or '' for all.
        unresolved_only: When True, already-resolved comments are excluded.

    Returns:
        List of comment objects with id, scope, file_path, text, author,
        resolved, created_at. Empty list when no matching comments exist.

    Errors:
        not_found — workspace not detected (handled by decorator).

    Example:
        workspace_get_comments(scope='review', unresolved_only=True)
    """
    return comment_service.get_comments(
        db, ws["id"], scope=scope or None, unresolved_only=unresolved_only
    )


@mcp.tool(annotations=ToolAnnotations(
    title="Post Comment",
    readOnlyHint=False,
    idempotentHint=False,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_post_comment(
    ws, project, db, locale,
    file_path: Annotated[str, Field(description=(
        "Path to the file being commented on, relative to the workspace root."
    ))],
    line_start: Annotated[int, Field(description=(
        "1-based line number where the comment range begins."
    ), ge=1)],
    line_end: Annotated[int, Field(description=(
        "1-based line number where the comment range ends. Must be >= line_start."
    ), ge=1)],
    text: Annotated[str, Field(description=(
        "The review comment body. Cannot be empty."
    ))],
    parent_id: Annotated[int, Field(description=(
        "ID of an existing comment to reply to. Use 0 to create a new root comment."
    ))] = 0,
) -> dict:
    """Post a review comment on specific file lines.

    Purpose:
        Called by code-reviewer agents during review phases to annotate
        a line range in a specific file. Each call creates a new comment row
        (not idempotent — duplicate calls produce duplicate comments).

    Parameters:
        file_path: Relative path from the workspace root.
        line_start: First line of the commented range (1-based, must be >= 1).
        line_end: Last line of the commented range (1-based, must be >= line_start).
        text: Comment body. Must be non-empty.
        parent_id: Set to an existing comment ID to thread a reply; 0 for root.

    Returns:
        {"ok": True, "id": <new-comment-id>} on success.

    Errors:
        validation — file_path or text is empty.
        not_found  — parent_id > 0 but no matching comment in this workspace.

    Example:
        workspace_post_comment("src/auth.py", 42, 55, "Missing null-check.", 0)
    """
    if not file_path or not file_path.strip():
        return mcp_error("validation", t("mcp.error.filePathRequired", locale), retryable=False)
    if not text or not text.strip():
        return mcp_error("validation", t("mcp.error.textRequired", locale), retryable=False)

    if parent_id > 0:
        parent = db.execute(
            "SELECT id FROM discussions WHERE id = ? AND workspace_id = ?",
            (parent_id, ws["id"])
        ).fetchone()
        if not parent:
            return mcp_error(
                "not_found",
                t("mcp.error.parentCommentNotFound", locale, id=parent_id),
                retryable=False,
                details={"parent_id": parent_id},
            )

    result = comment_service.post_comment(
        db, ws["id"], text=text.strip(), scope="review", author="agent",
        target=file_path.strip(), file_path=file_path.strip(),
        line_start=line_start, line_end=line_end,
        parent_id=parent_id if parent_id > 0 else None,
    )
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(
    title="Resolve Comment",
    readOnlyHint=False,
    idempotentHint=True,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_resolve_comment(
    ws, project, db, locale,
    comment_id: Annotated[int, Field(description=(
        "ID of the comment to resolve. Obtain from workspace_get_comments or "
        "workspace_get_state. Must belong to the current workspace."
    ))],
) -> dict:
    """Mark a user comment as resolved.

    Purpose:
        Sets the resolved flag on a non-review comment after the feedback has
        been addressed. Setting the same comment to resolved a second time is
        a no-op (idempotent).

    Parameters:
        comment_id: The ID of the comment to resolve.

    Returns:
        {"ok": True, "comment_id": <id>, "resolved": True} on success.

    Errors:
        not_found — comment_id does not exist or belongs to a different workspace.
        business  — comment has scope='review'; use workspace_resolve_review_issue
                    for review-scope items.

    Example:
        workspace_resolve_comment(17)
    """
    result = comment_service.resolve_comment(db, comment_id, ws["id"], block_review_scope=True, locale=locale)
    if "ok" in result:
        db.commit()
    if "error" in result:
        category = "business" if "review" in result["error"].lower() else "not_found"
        return mcp_error(category, result["error"], retryable=False, details={"comment_id": comment_id})
    return result


@mcp.tool(annotations=ToolAnnotations(
    title="Submit Review Issue",
    readOnlyHint=False,
    idempotentHint=False,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_submit_review_issue(
    ws, project, db, locale,
    file_path: Annotated[str, Field(description=(
        "Path to the file containing the issue, relative to the workspace root."
    ))],
    line_start: Annotated[int, Field(description=(
        "1-based line number where the issue begins."
    ), ge=1)],
    line_end: Annotated[int, Field(description=(
        "1-based line number where the issue ends. Must be >= line_start."
    ), ge=1)],
    severity: Annotated[Literal["critical", "major"], Field(description=(
        "Issue severity. 'critical' for blocking defects, 'major' for significant "
        "problems. Minor/style issues must not be submitted — use inline comments instead."
    ))],
    description: Annotated[str, Field(description=(
        "What the issue is and why it matters. Must be non-empty."
    ))],
    reviewer_name: Annotated[Literal["reviewer", "codex"], Field(description=(
        "Identity of the reviewer submitting the finding. Use 'reviewer' for the "
        "default review agent, 'codex' for Codex-authored findings."
    ))] = "reviewer",
) -> dict:
    """Submit a code review finding (critical or major severity only).

    Purpose:
        Called by reviewer agents to record a structured finding on a specific
        file and line range. Each call creates a new review-issue row — not
        idempotent. Only critical and major severities are accepted; the Literal
        type enforces this before the call reaches the service.

    Parameters:
        file_path: Relative path from workspace root. File must exist on disk.
        line_start: Start of the problem range (1-based, validated against file length).
        line_end: End of the problem range (>= line_start, validated here).
        severity: 'critical' or 'major'.
        description: Human-readable explanation of the defect.
        reviewer_name: 'reviewer' or 'codex'.

    Returns:
        {"ok": True, "id": <new-issue-id>} on success.

    Errors:
        validation — line_start > line_end, line_start beyond file, or empty description.
        not_found  — file_path does not exist under the workspace working_dir.
        transient  — file could not be read (I/O error).

    Example:
        workspace_submit_review_issue("src/auth.py", 42, 55, "critical",
            "Token is logged in plain text.", "reviewer")
    """
    if line_start > line_end:
        return mcp_error(
            "validation",
            t("mcp.error.lineStartBeyondLineEnd", locale),
            retryable=False,
            details={"line_start": line_start, "line_end": line_end},
        )

    working_dir = ws["working_dir"]
    full_path = Path(working_dir) / file_path
    if not full_path.exists():
        return mcp_error(
            "not_found",
            t("mcp.error.fileNotFound", locale, file_path=file_path),
            retryable=False,
            details={"file_path": file_path},
        )

    try:
        lines = full_path.read_text().splitlines()
        start = max(0, line_start - 1)
        if start >= len(lines):
            return mcp_error(
                "validation",
                t("mcp.error.lineStartBeyondFile", locale, line_start=line_start, length=len(lines)),
                retryable=False,
                details={"line_start": line_start, "file_length": len(lines)},
            )
    except Exception as e:
        return mcp_error(
            "transient",
            t("mcp.error.failedToReadFile", locale, error=str(e)),
            retryable=True,
            details={"file_path": file_path, "error": str(e)},
        )

    result = comment_service.submit_review_issue(
        db, ws["id"], file_path, line_start, line_end, description, author=reviewer_name
    )
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(
    title="Get Review Issues",
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_get_review_issues(
    ws, project, db, locale,
    status: Annotated[str, Field(description=(
        "Filter by resolution status: 'open', 'fixed', 'false_positive', or 'out_of_scope'. "
        "Empty string returns all issues regardless of status."
    ))] = "",
) -> list:
    """Get all review issues for the current workspace.

    Purpose:
        Returns the structured review-issue list (richer than workspace_get_comments
        for the review scope). Use this after a review phase to inspect findings,
        their severity, and current resolution state.

    Parameters:
        status: Optional resolution filter. One of 'open', 'fixed',
                'false_positive', 'out_of_scope', or '' for all.

    Returns:
        List of review-issue objects with id, file_path, line_start, line_end,
        severity, description, resolution, author, resolved, created_at.
        Empty list when no issues match.

    Errors:
        not_found — workspace not detected (handled by decorator).

    Example:
        workspace_get_review_issues(status='open')
    """
    return comment_service.get_review_issues(
        db, ws["id"], resolution=status or None
    )


@mcp.tool(annotations=ToolAnnotations(
    title="Resolve Review Issue",
    readOnlyHint=False,
    idempotentHint=True,
    destructiveHint=False,
))
@with_mcp_workspace
def workspace_resolve_review_issue(
    ws, project, db, locale,
    issue_id: Annotated[int, Field(description=(
        "ID of the review issue to resolve. Obtain from workspace_get_review_issues."
    ))],
    resolution: Annotated[Literal["fixed", "false_positive", "out_of_scope", "open"], Field(description=(
        "How the issue was addressed: "
        "'fixed' — code changed to eliminate the defect; "
        "'false_positive' — issue is invalid, code is correct as-is; "
        "'out_of_scope' — legitimate issue but outside the allowed change scope; "
        "'open' — resets to unresolved (used by review-validator to reopen issues)."
    ))],
) -> dict:
    """Set the resolution on a review issue.

    Purpose:
        Called by agents after addressing a review finding. Setting the same
        resolution a second time is a no-op (idempotent). The 'open' value
        is reserved for the review-validator agent to reopen issues that were
        incorrectly closed.

    Parameters:
        issue_id: Review item ID from workspace_get_review_issues.
        resolution: One of 'fixed', 'false_positive', 'out_of_scope', 'open'.

    Returns:
        {"ok": True, ...} on success.

    Errors:
        not_found — issue_id does not exist or belongs to a different workspace.

    Example:
        workspace_resolve_review_issue(7, "fixed")
    """
    _VALID_RESOLUTIONS = ("fixed", "false_positive", "out_of_scope", "open")
    if resolution not in _VALID_RESOLUTIONS:
        return mcp_error(
            "validation",
            t("mcp.error.invalidResolution", locale),
            retryable=False,
            details={"allowed": list(_VALID_RESOLUTIONS), "resolution": resolution},
        )

    result = comment_service.resolve_review_issue(
        db, issue_id, ws["id"], resolution, locale=locale
    )
    if "ok" in result:
        db.commit()
    if "error" in result:
        return mcp_error(
            "not_found",
            result["error"],
            retryable=False,
            details={"issue_id": issue_id},
        )
    return result
