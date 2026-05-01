"""MCP tools for managing work modes (named phase-set presets)."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import TRANSIENT_DB_EXCEPTIONS, mcp, mcp_error, with_global_db
from services import work_mode_service
from services.work_mode_service import WorkModeServiceError


def _translate_work_mode_error(exc: WorkModeServiceError) -> dict:
    if exc.code == "not_found":
        return mcp_error("not_found", str(exc), retryable=False, details=exc.details)
    if exc.code == "name_collision":
        return mcp_error("business", str(exc), retryable=False, details=exc.details)
    if exc.code == "invalid_phases":
        return mcp_error("validation", str(exc), retryable=False, details=exc.details)
    if exc.code == "system_immutable":
        return mcp_error("business", str(exc), retryable=False, details=exc.details)
    return mcp_error("business", str(exc), retryable=False)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create work mode",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_global_db
def work_mode_create(
    db,
    name: Annotated[str, Field(description="Unique mode name shown in the UI (e.g. 'fast-track', 'audit-only').", min_length=1)],
    description: Annotated[str, Field(description="Free-form description of when to use this mode.")] = "",
    phases: Annotated[list[dict], Field(description="Ordered list of phase entries. Each entry: {phase_id: str, enabled: bool}. Empty list is allowed and yields a mode that disables all phases.")] = [],
) -> dict:
    """Create a new user work mode.

    Purpose
      Persist a named phase-set preset that can later be assigned to one or
      more workspaces. System modes (built-ins) cannot be created through this
      API and have a name_collision-safe namespace.

    Returns
      Full mode dict (id, name, description, phases, origin='user',
      created_at, updated_at, used_by_count).

    Errors
      validation  — phases entries malformed (missing phase_id, bad types).
      business    — name collides with an existing mode (name_collision).
      transient   — DB failure; caller should retry.
    """
    try:
        result = work_mode_service.create(
            db,
            name=name,
            description=description,
            phases=list(phases or []),
        )
        db.commit()
        return result
    except WorkModeServiceError as exc:
        return _translate_work_mode_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="List work modes",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def work_mode_list(db) -> list:
    """List every work mode (system + user), ordered as the UI expects.

    Returns
      List of mode dicts. Each entry includes origin ('system'|'user') and
      used_by_count (workspaces currently assigned to that mode).

    Errors
      transient  — DB failure; caller should retry.
    """
    try:
        return work_mode_service.list_modes(db)
    except WorkModeServiceError as exc:
        return [_translate_work_mode_error(exc)]
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return [mcp_error("transient", str(exc), retryable=True)]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get work mode",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def work_mode_get(
    db,
    mode_id: Annotated[int, Field(description="Work mode ID returned by work_mode_create or work_mode_list.", ge=1)],
) -> dict:
    """Fetch a single work mode by ID.

    Returns
      Full mode dict (id, name, description, phases, origin, used_by_count, ...).

    Errors
      not_found  — mode_id does not exist.
      transient  — DB failure; caller should retry.
    """
    try:
        return work_mode_service.get(db, mode_id)
    except WorkModeServiceError as exc:
        return _translate_work_mode_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update work mode",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def work_mode_update(
    db,
    mode_id: Annotated[int, Field(description="Work mode ID to update.", ge=1)],
    name: Annotated[str | None, Field(description="New name. None = keep current.")] = None,
    description: Annotated[str | None, Field(description="New description. None = keep current.")] = None,
    phases: Annotated[list[dict] | None, Field(description="New ordered phase list. None = keep current. Empty list clears all phases.")] = None,
) -> dict:
    """Update an existing user work mode. Only provided fields are changed.

    Purpose
      Partial update: pass None for fields you want to leave alone. System
      modes are immutable and raise system_immutable.

    Returns
      Full updated mode dict.

    Errors
      not_found    — mode_id does not exist.
      business     — mode is a system mode (system_immutable) or name collides
                     with another mode (name_collision).
      validation   — phases entries malformed.
      transient    — DB failure; caller should retry.
    """
    try:
        result = work_mode_service.update(
            db,
            mode_id,
            name=name,
            description=description,
            phases=list(phases) if phases is not None else None,
        )
        db.commit()
        return result
    except WorkModeServiceError as exc:
        return _translate_work_mode_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Assign work mode",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def work_mode_assign(
    db,
    workspace_id: Annotated[int, Field(description="Workspace numeric ID (from the workspaces table) to assign the mode to.", ge=1)],
    mode_id: Annotated[int, Field(description="Work mode ID to assign as the workspace's active mode.", ge=1)],
) -> dict:
    """Assign a work mode to a workspace (sets the FK only, does not re-resolve).

    Purpose
      Persist the workspace's preferred mode. The change does not affect the
      workspace's active phase list until work_mode_apply is called.

    Returns
      {workspace_id, mode_id, mode_name, assigned_at}.

    Errors
      not_found  — mode_id or workspace_id does not exist.
      transient  — DB failure; caller should retry.
    """
    try:
        result = work_mode_service.assign(db, workspace_id, mode_id)
        db.commit()
        return result
    except WorkModeServiceError as exc:
        return _translate_work_mode_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Apply work mode",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def work_mode_apply(
    db,
    workspace_id: Annotated[int, Field(description="Workspace numeric ID whose assigned mode should be re-resolved into its effective phase list.", ge=1)],
) -> dict:
    """Re-resolve the assigned mode into the workspace's effective phase list.

    Purpose
      Triggers phase_resolver re-resolution and persists the result on the
      workspace. Idempotent: applying again with no underlying changes returns
      the same effective phase list.

    Returns
      {workspace_id, mode_id, mode_name, effective_phases: [...]}.

    Errors
      not_found  — workspace_id does not exist or has no assigned mode.
      transient  — DB failure; caller should retry.
    """
    try:
        result = work_mode_service.apply(db, workspace_id)
        db.commit()
        return result
    except WorkModeServiceError as exc:
        return _translate_work_mode_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
