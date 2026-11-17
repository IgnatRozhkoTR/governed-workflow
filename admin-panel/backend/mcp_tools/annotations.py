"""MCP tools for code annotations: short explanatory notes on a file's line range.

Annotations are reader context, not review comments — no replies, no
resolution, never gate-blocking — so they are allowed in every phase.
"""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import mcp, mcp_error, with_mcp_workspace
from services import annotation_service

_DEFAULT_AGENT_AUTHOR = "agent"
_NOT_FOUND_CODES = frozenset({"not_found", "file_not_found", "repo_not_found"})

_REPO_DESCRIPTION = (
    "Multi-repo workspaces only: rel_path of the attached repo the file belongs to. "
    "Leave empty for single-repo workspaces."
)
_FILE_PATH_DESCRIPTION = "File path relative to the repo root, e.g. 'src/billing/invoice.py'."
_LINE_START_DESCRIPTION = "First annotated line, 1-based."
_LINE_END_DESCRIPTION = "Last annotated line, 1-based and inclusive. Equal to line_start for a single line."
_TEXT_DESCRIPTION = "Markdown, 1-3 sentences explaining WHY (decision, trade-off, business reason)."


def _error_envelope(exc, locale: str) -> dict:
    category = "not_found" if exc.code in _NOT_FOUND_CODES else "validation"
    return mcp_error(category, exc.message(locale), retryable=False, details={"code": exc.code})


@mcp.tool(annotations=ToolAnnotations(
    title="Annotate code",
    readOnlyHint=False,
    idempotentHint=False,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_annotate(
    ws, project, db, locale,
    file_path: Annotated[str, Field(description=_FILE_PATH_DESCRIPTION)],
    line_start: Annotated[int, Field(description=_LINE_START_DESCRIPTION)],
    line_end: Annotated[int, Field(description=_LINE_END_DESCRIPTION)],
    text: Annotated[str, Field(description=_TEXT_DESCRIPTION)],
    repo: Annotated[str, Field(description=_REPO_DESCRIPTION)] = "",
    author: Annotated[str, Field(description="Your agent role, e.g. 'middle-backend-engineer'.")] = _DEFAULT_AGENT_AUTHOR,
) -> dict:
    """Attach an explanatory note to a line range of a file in the working tree.

    Use for non-obvious decisions, trade-offs and business reasons a reader or
    reviewer would ask about — see the `annotations` skill. Not for review
    findings (use review threads) or TODOs. Check workspace_list_annotations
    first and update an existing note instead of adding a duplicate.

    Returns:
        {"id", "repo", "file_path", "line_start", "line_end", "text", "author", "stale", "created_at", "updated_at"}.

    Errors:
        validation  — empty text, non-integer lines, range outside the file, bad path or repo.
        not_found   — file or repo does not exist.
    """
    try:
        annotation = annotation_service.create_annotation(
            db, ws, project, repo=repo, file_path=file_path, line_start=line_start,
            line_end=line_end, text=text, author=author.strip() or _DEFAULT_AGENT_AUTHOR,
        )
    except annotation_service.AnnotationServiceError as exc:
        return _error_envelope(exc, locale)
    db.commit()
    return annotation


@mcp.tool(annotations=ToolAnnotations(
    title="Update annotation",
    readOnlyHint=False,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_update_annotation(
    ws, project, db, locale,
    id: Annotated[int, Field(description="Annotation id from workspace_list_annotations.")],
    text: Annotated[str | None, Field(description="New markdown text. Omit to keep the current text.")] = None,
    line_start: Annotated[int | None, Field(description="New first line. Omit to keep the current one.")] = None,
    line_end: Annotated[int | None, Field(description="New last line. Omit to keep the current one.")] = None,
) -> dict:
    """Change an annotation's text and/or move it to a new line range.

    A new range re-captures the anchor from the file's current working-tree
    content — use it to re-attach a stale annotation after the code moved.

    Returns:
        The updated annotation, same shape as workspace_annotate.

    Errors:
        validation  — nothing to update, empty text, or range outside the file.
        not_found   — no annotation with this id in this workspace, or its file is gone.
    """
    try:
        annotation = annotation_service.update_annotation(
            db, ws, project, id, text=text, line_start=line_start, line_end=line_end,
        )
    except annotation_service.AnnotationServiceError as exc:
        return _error_envelope(exc, locale)
    db.commit()
    return annotation


@mcp.tool(annotations=ToolAnnotations(
    title="Delete annotation",
    readOnlyHint=False,
    idempotentHint=False,
    destructiveHint=True,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_delete_annotation(
    ws, project, db, locale,
    id: Annotated[int, Field(description="Annotation id from workspace_list_annotations.")],
) -> dict:
    """Delete an annotation that no longer applies (the explained code was removed or rewritten).

    Returns:
        {"ok": True, "id"}.

    Errors:
        not_found   — no annotation with this id in this workspace.
    """
    try:
        annotation_service.delete_annotation(db, ws["id"], id)
    except annotation_service.AnnotationServiceError as exc:
        return _error_envelope(exc, locale)
    db.commit()
    return {"ok": True, "id": id}


@mcp.tool(annotations=ToolAnnotations(
    title="List annotations",
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def workspace_list_annotations(
    ws, project, db, locale,
    file_path: Annotated[str, Field(description=(
        "Limit to one file and resolve each annotation against its current working-tree content "
        "(stale=true when its lines changed beyond recognition). Leave empty to list every "
        "annotation in the workspace at its stored lines."
    ))] = "",
    repo: Annotated[str, Field(description=_REPO_DESCRIPTION)] = "",
) -> list:
    """List the author's explanatory annotations — read them for context on why code is the way it is.

    Returns:
        List of {"id", "repo", "file_path", "line_start", "line_end", "text", "author", "stale", "created_at", "updated_at"}.

    Errors (as a single-element list):
        validation  — bad path or repo.
        not_found   — file or repo does not exist.
    """
    if not file_path.strip():
        return annotation_service.list_annotations(db, ws["id"])
    try:
        return annotation_service.list_file_annotations(db, ws, project, repo=repo, file_path=file_path)
    except annotation_service.AnnotationServiceError as exc:
        return [_error_envelope(exc, locale)]
