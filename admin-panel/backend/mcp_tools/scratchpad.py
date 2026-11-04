"""MCP tools for managing human-facing scratchpad reports under .claude/scratchpad/."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import mcp, mcp_error, with_mcp_workspace
from services import scratchpad_service
from services.scratchpad_service import ScratchpadServiceError

_REPO_DESCRIPTION = (
    "Multi-repo projects only: rel_path or name of an attached repo to scope this "
    "scratchpad to that repo's own .claude/scratchpad/ directory. Leave empty for "
    "the workspace root."
)

_ERROR_CODE_TO_CATEGORY = {
    "not_found": "not_found",
    "already_exists": "business",
    "no_match": "business",
    "ambiguous_match": "business",
    "invalid_name": "validation",
    "invalid_repo": "validation",
    "repo_required": "validation",
    "repo_not_found": "not_found",
}

_ERROR_CODE_MESSAGE = {
    "invalid_repo": "repo contains an invalid or unsafe path.",
    "repo_required": "repo is required for this multi-repo workspace.",
    "repo_not_found": "repo does not match any attached repo.",
}


def _translate_error(code: str, message: str) -> dict:
    category = _ERROR_CODE_TO_CATEGORY.get(code, "business")
    return mcp_error(category, message, retryable=False, details={"code": code})


def _resolve_dir_or_error(ws, project, db, repo: str):
    """Return (scratchpad_dir, None) or (None, error_envelope)."""
    scratchpad_dir, err = scratchpad_service.resolve_scratchpad_dir(db, ws, project, repo.strip())
    if err:
        return None, _translate_error(err, _ERROR_CODE_MESSAGE.get(err, err))
    return scratchpad_dir, None


def _resolve_name_or_error(name: str):
    """Return (normalized_name, None) or (None, error_envelope)."""
    normalized = scratchpad_service.normalize_name(name)
    name_err = scratchpad_service.validate_name(normalized)
    if name_err:
        return None, _translate_error(name_err, f"Invalid scratchpad name '{name}'.")
    return normalized, None


@mcp.tool(annotations=ToolAnnotations(
    title="Create scratchpad",
    readOnlyHint=False,
    idempotentHint=False,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def scratchpad_create(
    ws, project, db, locale,
    name: Annotated[str, Field(description="Kebab-case filename for the scratchpad, e.g. 'migration-plan'. '.md' is appended if omitted.")],
    content: Annotated[str, Field(description="Markdown body. Should start with '# Title' — that title is shown in the panel's Scratchpads tab.")],
    repo: Annotated[str, Field(description=_REPO_DESCRIPTION)] = "",
) -> dict:
    """Create a new human-facing scratchpad report. Fails if one already exists at that name.

    Returns:
        {"name", "path", "title", "updated_at"} on success.

    Errors:
        business    — a scratchpad with this name already exists.
        validation  — the name is invalid, or repo is malformed for this project.
        not_found   — repo does not match any attached repo.
    """
    scratchpad_dir, error = _resolve_dir_or_error(ws, project, db, repo)
    if error:
        return error
    resolved_name, error = _resolve_name_or_error(name)
    if error:
        return error

    try:
        return scratchpad_service.create_scratchpad(scratchpad_dir, resolved_name, content)
    except ScratchpadServiceError as exc:
        return _translate_error(exc.code, str(exc))


@mcp.tool(annotations=ToolAnnotations(
    title="Replace scratchpad",
    readOnlyHint=False,
    idempotentHint=True,
    destructiveHint=True,
    openWorldHint=False,
))
@with_mcp_workspace
def scratchpad_replace(
    ws, project, db, locale,
    name: Annotated[str, Field(description="Filename of the existing scratchpad to overwrite.")],
    content: Annotated[str, Field(description="New markdown body that fully replaces the old one.")],
    repo: Annotated[str, Field(description=_REPO_DESCRIPTION)] = "",
) -> dict:
    """Overwrite an existing scratchpad's full content. Fails if it does not exist.

    Returns:
        {"name", "path", "title", "updated_at"} on success.

    Errors:
        not_found   — no scratchpad with this name exists, or repo does not match.
        validation  — the name is invalid, or repo is malformed for this project.
    """
    scratchpad_dir, error = _resolve_dir_or_error(ws, project, db, repo)
    if error:
        return error
    resolved_name, error = _resolve_name_or_error(name)
    if error:
        return error

    try:
        return scratchpad_service.replace_scratchpad(scratchpad_dir, resolved_name, content)
    except ScratchpadServiceError as exc:
        return _translate_error(exc.code, str(exc))


@mcp.tool(annotations=ToolAnnotations(
    title="Patch scratchpad",
    readOnlyHint=False,
    idempotentHint=False,
    destructiveHint=False,
    openWorldHint=False,
))
@with_mcp_workspace
def scratchpad_patch(
    ws, project, db, locale,
    name: Annotated[str, Field(description="Filename of the existing scratchpad to edit.")],
    old_string: Annotated[str, Field(description="Exact text to replace. Must occur exactly once in the file.")],
    new_string: Annotated[str, Field(description="Text to put in its place.")],
    repo: Annotated[str, Field(description=_REPO_DESCRIPTION)] = "",
) -> dict:
    """Replace one exact occurrence of old_string with new_string in an existing scratchpad.

    Returns:
        {"name", "path", "title", "updated_at"} on success.

    Errors:
        not_found   — no scratchpad with this name exists, or repo does not match.
        business    — old_string is not found, or occurs more than once.
        validation  — the name is invalid, or repo is malformed for this project.
    """
    scratchpad_dir, error = _resolve_dir_or_error(ws, project, db, repo)
    if error:
        return error
    resolved_name, error = _resolve_name_or_error(name)
    if error:
        return error

    try:
        return scratchpad_service.patch_scratchpad(scratchpad_dir, resolved_name, old_string, new_string)
    except ScratchpadServiceError as exc:
        return _translate_error(exc.code, str(exc))


@mcp.tool(annotations=ToolAnnotations(
    title="Delete scratchpad",
    readOnlyHint=False,
    idempotentHint=True,
    destructiveHint=True,
    openWorldHint=False,
))
@with_mcp_workspace
def scratchpad_delete(
    ws, project, db, locale,
    name: Annotated[str, Field(description="Filename of the scratchpad to delete.")],
    repo: Annotated[str, Field(description=_REPO_DESCRIPTION)] = "",
) -> dict:
    """Delete an existing scratchpad. Fails if it does not exist.

    Returns:
        {"ok": True, "name"} on success.

    Errors:
        not_found   — no scratchpad with this name exists, or repo does not match.
        validation  — the name is invalid, or repo is malformed for this project.
    """
    scratchpad_dir, error = _resolve_dir_or_error(ws, project, db, repo)
    if error:
        return error
    resolved_name, error = _resolve_name_or_error(name)
    if error:
        return error

    try:
        scratchpad_service.delete_scratchpad(scratchpad_dir, resolved_name)
    except ScratchpadServiceError as exc:
        return _translate_error(exc.code, str(exc))
    return {"ok": True, "name": resolved_name}
