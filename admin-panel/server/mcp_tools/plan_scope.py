from typing import Annotated, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import mcp, mcp_error, with_mcp_workspace
from core.i18n import t
from services import plan_service
from services import scope_service


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False))
@with_mcp_workspace
def workspace_set_scope(
    ws, project, db, locale,
    scope: Annotated[dict, Field(description="Phase-keyed map {phase_id: {must: [...], may: [...]}}.")]
) -> dict:
    """Set workspace scope as a phase-keyed map. Allowed from phase 1 onwards.

    Setting scope automatically revokes approval — the user must review and re-approve
    the new scope in the admin panel before code edits are allowed.

    Format: {"3.1": {"must": ["src/models/"], "may": ["src/config/"]}, "3.2": {...}}
    Each key is a sub-phase ID from the execution plan.
    'must' paths MUST have changes for the phase to advance.
    'may' paths are permitted but not required.

    Same scope set twice is a no-op on content but still revokes approval."""
    result = scope_service.set_scope(db, ws, scope)
    if "error" in result:
        return mcp_error("validation", result["error"], retryable=False)
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False))
@with_mcp_workspace
def workspace_set_plan(
    ws, project, db, locale,
    plan: Annotated[dict, Field(description="Plan JSON — see docstring for schema.")]
) -> dict:
    """Set the execution plan. Editable during and after planning (phase >= 2.0).

    The previous plan is saved automatically — call workspace_restore_plan to revert
    if the new plan has not been approved yet. Setting a plan revokes approval.

    Expected format:
    {
        "description": "High-level plain text description of what this plan achieves",
        "systemDiagram": [{"title": "Class Diagram", "diagram": "classDiagram\\n..."},
                          {"title": "Auth Flow", "diagram": "sequenceDiagram\\n..."}],
        "execution": [
            {
                "id": "3.1",
                "name": "Sub-phase name",
                "tasks": [{"title": "...", "files": ["..."], "agent": "...",
                           "status": "pending", "group": "optional group"}]
            }
        ]
    }

    systemDiagram must be an array of {title: str, diagram: str} objects (Mermaid syntax).
    Include at minimum one class/entity diagram and one sequence diagram.

    Tasks with the same "group" name run in parallel. Tasks without a group run
    sequentially. Scope is set separately via workspace_set_scope."""
    result = plan_service.set_plan(db, ws, plan)
    if "error" in result:
        return mcp_error("business", result["error"], retryable=False)
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False))
@with_mcp_workspace
def workspace_get_plan(ws, project, db, locale) -> dict:
    """Get the full execution plan including system diagram and all sub-phases with tasks.

    Returns the complete plan JSON: description, systemDiagram array, and execution
    array with tasks per sub-phase. Use workspace_get_state to see the current scope map
    and approval status."""
    return plan_service.get_plan(ws)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False))
@with_mcp_workspace
def workspace_extend_plan(
    ws, project, db, locale,
    subphase: Annotated[dict, Field(description="New sub-phase spec: {name: str, tasks: list[dict], scope?: dict, diagrams?: list[dict]}. Appended at the end; ID is auto-assigned.")],
    scope: Annotated[dict, Field(description="Scope for this sub-phase with must/may patterns, e.g. {\"must\": [\"src/foo/\"], \"may\": [\"src/bar/\"]}.")],
    diagrams: Annotated[Optional[list], Field(description="Optional diagrams to add, each {title: str, diagram: str}.")] = None,
    replace_diagrams: Annotated[bool, Field(description="If True, replace the plan's existing systemDiagram entirely. If False (default), append new diagrams from subphase.diagrams to existing ones.")] = False,
) -> dict:
    """Append a new sub-phase to the execution plan without rewriting existing sub-phases.

    The sub-phase 'id' is auto-assigned as 3.(max_n+1). Each call appends a new entry
    (not idempotent — calling twice creates two sub-phases).

    subphase: dict with 'name' (string) and 'tasks' (list). Each task needs:
      title (string), files (list), agent (string).
      Optional task fields: group (string), status (string, default 'pending').
    scope: must/may scope entry for the new sub-phase.
    diagrams: optional list of {title, diagram} objects to add. Appended by default;
      set replace_diagrams=True to replace the entire diagram list instead.

    plan_status and scope_status are set to 'pending'. Existing sub-phases are unchanged."""
    result = plan_service.extend_plan(db, ws, subphase, scope, diagrams, replace_diagrams)
    if "error" in result:
        return mcp_error("validation", result["error"], retryable=False)
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False))
@with_mcp_workspace
def workspace_restore_plan(ws, project, db, locale) -> dict:
    """Restore the most recently saved previous plan.

    Only works if current plan is NOT approved. Call this before the user approves
    if you need to revert an incorrectly set plan.

    The previous plan's phase position is also restored."""
    if not ws["prev_plan_json"]:
        return mcp_error("not_found", t("mcp.error.noPreviousPlan", locale), retryable=False)

    if ws["plan_status"] == "approved":
        return mcp_error("business", t("mcp.error.planApproved", locale), retryable=False)

    new_ws = plan_service.restore_plan(db, ws)
    db.commit()

    return {
        "ok": True,
        "restored": True,
        "phase": new_ws["phase"],
        "plan_status": new_ws["plan_status"],
        "message": t("mcp.restorePlan.message", locale, phase=new_ws["phase"]),
    }
