from typing import Annotated, Literal, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import (
    TRANSIENT_DB_EXCEPTIONS,
    mcp,
    mcp_error,
    translate_service_error,
    with_global_db,
    with_mcp_workspace,
)
from core.i18n import t
from services import verification_service

_FAIL_SEVERITY = Literal["blocking", "warning"]

_PROFILE_ERROR_MAPPING = {
    "profile_not_found": ("not_found", False),
    "no_fields_to_update": ("validation", False),
}

_STEP_ERROR_MAPPING = {
    "profile_not_found": ("not_found", False),
}

_ASSIGN_ERROR_MAPPING = {
    "profile_not_found": ("not_found", False),
}


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get verification results",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def workspace_get_verification_results(
    ws,
    project,
    db,
    locale,
    phase: Annotated[
        str,
        Field(description="Filter by phase string, e.g. '3.1.1'. Empty = latest run overall."),
    ] = "",
    run_id: Annotated[
        int,
        Field(description="Fetch a specific run by numeric ID. Takes precedence over phase. 0 = not specified.", ge=0),
    ] = 0,
) -> dict:
    """Get verification run results for the current workspace.

    Purpose
      Returns the most recent verification run for the workspace. Filters by
      phase string when provided; fetches an exact run when run_id is given.
      run_id takes precedence over phase when both are supplied.

    Parameters
      phase:  Phase string, e.g. '3.1.1'. Empty = return the latest run.
      run_id: Numeric run ID for exact lookup. 0 = not specified.

    Returns
      Run dict with status and per-step results. When no runs exist returns
      {"runs": [], "empty": True} — this is a valid empty result, not an error.

    Errors
      not_found — run_id was given but does not belong to this workspace.
      transient — DB failure; caller should retry.

    Example
      workspace_get_verification_results()
      workspace_get_verification_results(phase="3.1.1")
      workspace_get_verification_results(run_id=42)
    """
    try:
        result = verification_service.get_verification_results(
            db, ws["id"], phase=phase or None, run_id=run_id if run_id else None
        )
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)

    if result is None:
        if run_id:
            return mcp_error(
                "not_found",
                t("mcp.error.verificationRunNotFound", locale),
                retryable=False,
                details={"run_id": run_id},
            )
        return {"runs": [], "empty": True}
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get verification profiles",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def workspace_get_verification_profiles(db) -> list:
    """List all available verification profiles in the system.

    Purpose
      NOT workspace-bound — callable from any directory. Returns every
      verification profile together with its configured steps. Use
      workspace_assign_verification_profile to link one to the current project.

    Returns
      List of profile dicts, each with a nested 'steps' list. Empty list when
      none are configured — not an error.

    Errors
      transient — DB failure; caller should retry.

    Example
      workspace_get_verification_profiles()
    """
    try:
        return verification_service.get_all_profiles(db)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create verification profile",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_global_db
def workspace_create_verification_profile(
    db,
    name: Annotated[str, Field(description="Display name, e.g. 'Go', 'Java (Custom)'.", min_length=1)],
    language: Annotated[str, Field(description="Language key, e.g. 'go', 'rust', 'java'.", min_length=1)],
    description: Annotated[str, Field(description="What this profile checks.")] = "",
    lsp_command: Annotated[
        str,
        Field(description="LSP server binary, e.g. 'jdtls', 'pyright-langserver'. Required for LSP button to appear."),
    ] = "",
    lsp_args: Annotated[
        str,
        Field(description="JSON array of CLI args, e.g. '[\"--stdio\"]'. Optional."),
    ] = "",
    lsp_install_check_command: Annotated[
        str,
        Field(description="Command to check whether the LSP server is installed, e.g. 'which jdtls'. Optional."),
    ] = "",
    lsp_install_command: Annotated[
        str,
        Field(description="Command to install the LSP server, e.g. 'brew install jdtls'. Optional."),
    ] = "",
    lsp_workspace_config: Annotated[
        str,
        Field(description="JSON workspace config for the LSP server. Optional."),
    ] = "",
    lsp_port: Annotated[
        int,
        Field(description="Fixed port for the LSP server. 0 = auto-assign.", ge=0),
    ] = 0,
) -> dict:
    """Create a new verification profile. NOT workspace-bound.

    Purpose
      Profiles define language-level verification: which steps to run and how
      to start the LSP server. After creation, add steps with
      workspace_add_verification_step, then assign to a project with
      workspace_assign_verification_profile.

    Parameters
      name:        Display name, e.g. 'Go', 'Java (Custom)'.
      language:    Language key, e.g. 'go', 'rust', 'java'.
      description: What this profile checks.
      lsp_command: LSP server binary or shell command. Required for LSP button.
      lsp_args:    JSON array of CLI args.
      lsp_install_check_command: Shell command to verify LSP is installed.
      lsp_install_command: Shell command to install the LSP server.
      lsp_workspace_config: JSON workspace settings for the LSP.
      lsp_port:    Fixed port; 0 = auto-assign.

    Returns
      {ok: True, id: <int>}

    Errors
      validation — name or language is blank.
      transient  — DB failure; caller should retry.
    """
    if not name.strip():
        return mcp_error("validation", t("mcp.error.profileNameRequired"), retryable=False)
    if not language.strip():
        return mcp_error("validation", t("mcp.error.profileLanguageRequired"), retryable=False)

    try:
        result = verification_service.create_profile(
            db, name, language, description=description or None,
            lsp_command=lsp_command or None, lsp_args=lsp_args or None,
            lsp_install_check_command=lsp_install_check_command or None,
            lsp_install_command=lsp_install_command or None,
            lsp_workspace_config=lsp_workspace_config or None,
            lsp_port=lsp_port if lsp_port else None,
        )
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
    db.commit()
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update verification profile",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def workspace_update_verification_profile(
    db,
    profile_id: Annotated[int, Field(description="ID of the profile to update (from workspace_get_verification_profiles).", ge=1)],
    description: Annotated[Optional[str], Field(description="Updated description text. Omit to keep current.")] = None,
    lsp_command: Annotated[Optional[str], Field(description="LSP server binary or shell command. Pass '' to clear.")] = None,
    lsp_args: Annotated[Optional[str], Field(description="JSON array of CLI args. Pass '' to clear.")] = None,
    lsp_install_check_command: Annotated[Optional[str], Field(description="Command to check LSP installation. Pass '' to clear.")] = None,
    lsp_install_command: Annotated[Optional[str], Field(description="Command to install the LSP server. Pass '' to clear.")] = None,
    lsp_workspace_config: Annotated[Optional[str], Field(description="JSON workspace config for the LSP. Pass '' to clear.")] = None,
    lsp_port: Annotated[Optional[int], Field(description="Fixed port (0 = auto). Omit to keep current.", ge=0)] = None,
) -> dict:
    """Update LSP configuration and/or description on an existing profile. NOT workspace-bound.

    Purpose
      Only fields explicitly provided (non-None) are updated. Pass an empty
      string to clear a string field. Calling with only profile_id returns a
      validation error (no_fields_to_update).

    Parameters
      profile_id:                 ID of the profile to update.
      description:                New description text.
      lsp_command:                LSP server binary or shell command.
      lsp_args:                   JSON array of CLI args.
      lsp_install_check_command:  Check command for LSP installation.
      lsp_install_command:        Install command for the LSP server.
      lsp_workspace_config:       JSON workspace config.
      lsp_port:                   Fixed port; 0 = auto.

    Returns
      {ok: True}

    Errors
      not_found  — profile_id does not reference a known profile.
      validation — no fields were provided to update.
      transient  — DB failure; caller should retry.
    """
    kwargs = {}
    if description is not None:
        kwargs["description"] = description
    if lsp_command is not None:
        kwargs["lsp_command"] = lsp_command
    if lsp_args is not None:
        kwargs["lsp_args"] = lsp_args
    if lsp_install_check_command is not None:
        kwargs["lsp_install_check_command"] = lsp_install_check_command
    if lsp_install_command is not None:
        kwargs["lsp_install_command"] = lsp_install_command
    if lsp_workspace_config is not None:
        kwargs["lsp_workspace_config"] = lsp_workspace_config
    if lsp_port is not None:
        kwargs["lsp_port"] = lsp_port

    try:
        result = verification_service.update_profile(db, profile_id, **kwargs)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)

    if "error" in result:
        return translate_service_error(result, _PROFILE_ERROR_MAPPING)
    db.commit()
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Add verification step",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_global_db
def workspace_add_verification_step(
    db,
    profile_id: Annotated[int, Field(description="ID of the profile to add the step to.", ge=1)],
    name: Annotated[str, Field(description="Step name, e.g. 'Compilation', 'Lint'.", min_length=1)],
    command: Annotated[str, Field(description="Shell command to run as this step.", min_length=1)],
    description: Annotated[str, Field(description="Human-readable description of what this step checks.")] = "",
    install_check_command: Annotated[
        str,
        Field(description="Shell command to verify the tool is present before running. Optional."),
    ] = "",
    install_command: Annotated[
        str,
        Field(description="Shell command to install the tool when the check fails. Optional."),
    ] = "",
    enabled: Annotated[bool, Field(description="Whether this step runs. Default True.")] = True,
    sort_order: Annotated[int, Field(description="Execution order; lower numbers run first. 0 = first.", ge=0)] = 0,
    timeout: Annotated[int, Field(description="Step timeout in seconds. 0 = no timeout. Default 120.", ge=0)] = 120,
    fail_severity: Annotated[
        _FAIL_SEVERITY,
        Field(description="'blocking' stops phase advancement on failure; 'warning' is logged only."),
    ] = "blocking",
) -> dict:
    """Add a verification step to an existing profile. NOT workspace-bound.

    Purpose
      Steps define the individual commands that run during verification
      (e.g. compile, lint, test). Execution order is controlled by sort_order.
      Add all steps, then assign the profile to a project.

    Parameters
      profile_id:            Profile to attach this step to.
      name:                  Step name, e.g. 'Compilation'.
      command:               Shell command to execute.
      description:           What this step verifies.
      install_check_command: Checks whether the required tool is installed.
      install_command:       Installs the tool if the check fails.
      enabled:               Whether this step runs during verification.
      sort_order:            Lower = earlier in execution order.
      timeout:               Seconds before step is killed. 0 = unlimited.
      fail_severity:         blocking | warning.

    Returns
      {ok: True, id: <int>}

    Errors
      not_found  — profile_id does not reference a known profile.
      validation — fail_severity is not 'blocking' or 'warning'.
      transient  — DB failure; caller should retry.
    """
    try:
        result = verification_service.add_step(
            db, profile_id, name, command,
            description=description or None,
            install_check_command=install_check_command or None,
            install_command=install_command or None,
            enabled=enabled, sort_order=sort_order, timeout=timeout, fail_severity=fail_severity,
        )
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)

    if "error" in result:
        return translate_service_error(result, _STEP_ERROR_MAPPING)
    db.commit()
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Assign verification profile",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def workspace_assign_verification_profile(
    ws,
    project,
    db,
    locale,
    profile_id: Annotated[int, Field(description="ID of the profile to assign (from workspace_get_verification_profiles).", ge=1)],
    subpath: Annotated[
        str,
        Field(description="Subdirectory to run verification in. '.' = workspace root. Use for multi-language projects."),
    ] = ".",
) -> dict:
    """Assign a verification profile to the current project.

    Purpose
      Applies to all workspaces sharing the same project. Use subpath for
      multi-language repositories where different language profiles apply to
      different subdirectories. Assigning the same profile + subpath twice
      returns a business error (already_assigned).

    Parameters
      profile_id: ID from workspace_get_verification_profiles.
      subpath:    Relative subdirectory; '.' = root.

    Returns
      {ok: True, id: <int>}

    Errors
      not_found — profile_id does not reference a known profile.
      business  — the same profile is already assigned to this subpath.
      transient — DB failure; caller should retry.
    """
    try:
        result = verification_service.assign_profile(db, ws["project_id"], profile_id, subpath=subpath)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)

    if "error" in result:
        return translate_service_error(result, _ASSIGN_ERROR_MAPPING)
    db.commit()
    return result
