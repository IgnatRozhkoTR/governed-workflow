from typing import Annotated, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from core.db import ws_field
from mcp_tools import mcp, mcp_error, with_mcp_workspace
from services import plan_service

_PLAN_ERROR_CATEGORIES = {
    "subphase_not_found": "not_found",
    "cannot_delete_last_subphase": "business",
}


def _plan_error(result: dict) -> dict:
    """Wrap a plan_service error dict in the matching mcp_error envelope."""
    category = _PLAN_ERROR_CATEGORIES.get(result.get("errorCode"), "validation")
    return mcp_error(category, result["error"], retryable=False)


def _simple_mode_error(operation: str) -> dict:
    return mcp_error(
        "business",
        f"{operation} is not available in simple planning mode.",
        retryable=False,
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False))
@with_mcp_workspace
def workspace_set_plan(
    ws, project, db, locale,
    plan: Annotated[dict, Field(description="Plan JSON — see docstring for schema.")]
) -> dict:
    """Set the execution plan. Editable during and after planning (phase >= 2.0).

    Setting a plan revokes approval — the user must review and re-approve before
    the workflow can advance past planning. Approving the plan also approves its
    scope and accepts all proposed acceptance criteria.

    Expected format:
    {
        "description": "High-level plain text description of what this plan achieves",
        "systemDiagram": [{"title": "Class Diagram", "diagram": "classDiagram\\n..."},
                          {"title": "Auth Flow", "diagram": "sequenceDiagram\\n..."}],
        "execution": [
            {
                "id": "3.1",
                "name": "Sub-phase name",
                "scope": {"must": ["src/models/"], "may": ["src/config/"]},
                "tasks": [{"title": "...", "files": ["..."], "agent": "...",
                           "status": "pending", "group": "optional group"}]
            }
        ]
    }

    systemDiagram must be an array of {title: str, diagram: str} objects (Mermaid syntax).
    Include at minimum one class/entity diagram and one sequence diagram.

    Each execution item must carry a per-item "scope" object with a "must" list
    (a "may" list is optional). 'must' paths MUST have changes for the sub-phase
    to advance; 'may' paths are permitted but not required.

    Tasks with the same "group" name run in parallel. Tasks without a group run
    sequentially."""
    result = plan_service.set_plan(
        db, ws, plan,
        simple_mode=bool(project["simple_planning"]),
        fast_mode=ws_field(ws, "workflow_mode", "standard") == "fast",
    )
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
    subphase: Annotated[dict, Field(description="New sub-phase spec: {name: str, tasks: list[dict]}. Appended at the end; ID is auto-assigned. Scope and diagrams come from the separate 'scope' and 'diagrams' arguments.")],
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
    scope: must/may scope entry for the new sub-phase; embedded into the new
      execution item. A 'must' list is required.
    diagrams: optional list of {title, diagram} objects to add — passed as this
      top-level argument, not inside subphase. Appended by default; set
      replace_diagrams=True to replace the entire diagram list instead.

    plan_status is set to 'pending'. Existing sub-phases are unchanged."""
    if project["simple_planning"]:
        return _simple_mode_error("Extending the plan")

    result = plan_service.extend_plan(db, ws, subphase, scope, diagrams, replace_diagrams)
    if "error" in result:
        return mcp_error("validation", result["error"], retryable=False)
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(title="Update plan sub-phase", readOnlyHint=False, idempotentHint=True, destructiveHint=False))
@with_mcp_workspace
def workspace_update_subphase(
    ws, project, db, locale,
    subphase_id: Annotated[str, Field(description="ID of the execution item to patch, e.g. '3.2'.")],
    name: Annotated[str, Field(description="Replacement sub-phase name. Omit or pass empty to keep the current name.")] = "",
    tasks: Annotated[Optional[list], Field(description="Replacement task list, each {title: str, files: list, agent: str, group?: str, status?: str}. Omit or pass None to keep the current tasks.")] = None,
    scope: Annotated[Optional[dict], Field(description="Replacement scope, e.g. {\"must\": [\"src/foo/\"], \"may\": [\"src/bar/\"]}. Omit or pass None to keep the current scope.")] = None,
) -> dict:
    """Patch a single existing sub-phase without resubmitting the whole plan.

    Purpose
      Use this instead of workspace_set_plan when only one sub-phase changed —
      renaming it, reworking its tasks, or widening its scope. Every other
      sub-phase, the description and the diagrams are left untouched, and IDs are
      never renumbered.

    Parameters
      subphase_id: ID of the execution item to patch (e.g. '3.2').
      name: Replacement name. Empty = keep current.
      tasks: Replacement task list (fully replaces the existing one). None = keep current.
      scope: Replacement {must, may} scope object. None = keep current.

    Returns
      {ok: True, subphase: {...}, plan_status: "pending"}

    Errors
      not_found  — subphase_id is not in the plan.
      validation — nothing supplied to update, blank name, empty/malformed tasks,
                   scope without a 'must' list, or the workspace is before phase 2.0.
      business   — simple planning mode.

    Example
      workspace_update_subphase(subphase_id="3.2",
          scope={"must": ["src/api/"], "may": ["tests/api/"]})

    This is a structural change: plan_status is reset to 'pending' and the user
    must re-approve the plan."""
    if project["simple_planning"]:
        return _simple_mode_error("Updating a sub-phase")

    result = plan_service.update_subphase(
        db, ws, subphase_id, name=name or None, tasks=tasks, scope=scope,
    )
    if "error" in result:
        return _plan_error(result)
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(title="Delete plan sub-phase", readOnlyHint=False, idempotentHint=False, destructiveHint=True))
@with_mcp_workspace
def workspace_delete_subphase(
    ws, project, db, locale,
    subphase_id: Annotated[str, Field(description="ID of the execution item to remove, e.g. '3.2'.")],
) -> dict:
    """Remove one sub-phase from the plan and renumber the rest.

    Purpose
      Use this when a planned sub-phase turns out to be unnecessary. The
      remaining items keep their order and are renumbered to stay sequential
      (deleting 3.1 of three items leaves 3.1 and 3.2), because the advance gate
      requires execution IDs to be exactly 3.1, 3.2, … by position.

    Parameters
      subphase_id: ID of the execution item to remove (e.g. '3.2').

    Returns
      {ok: True, deleted_id, execution_ids: [...], phase, plan_status: "pending"}

    Errors
      not_found  — subphase_id is not in the plan.
      business   — it is the last remaining sub-phase; a plan needs at least one.
      validation — the workspace is before phase 2.0.

    Example
      workspace_delete_subphase(subphase_id="3.3")

    Renumbering can move the sub-phase the workspace is currently executing; when
    the current sub-phase no longer exists the workspace is rewound to 2.0.
    This is a structural change: plan_status is reset to 'pending' and the user
    must re-approve the plan."""
    if project["simple_planning"]:
        return _simple_mode_error("Deleting a sub-phase")

    result = plan_service.delete_subphase(db, ws, subphase_id)
    if "error" in result:
        return _plan_error(result)
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(title="Set plan diagrams", readOnlyHint=False, idempotentHint=True, destructiveHint=False))
@with_mcp_workspace
def workspace_set_plan_diagrams(
    ws, project, db, locale,
    diagrams: Annotated[list, Field(description="Diagrams as [{title: str, diagram: str}], diagram being Mermaid syntax.")],
    replace: Annotated[bool, Field(description="True (default) replaces the plan's diagram list. False appends to it.")] = True,
) -> dict:
    """Replace or append the plan's system diagrams without resubmitting the whole plan.

    Purpose
      Use this when only the diagrams changed — reworking a class diagram costs a
      few hundred tokens here instead of a full workspace_set_plan round-trip.
      The description and every execution item are left untouched.

    Parameters
      diagrams: List of {title, diagram} objects; diagram holds Mermaid syntax.
                An empty list with replace=True clears the diagrams.
      replace: True (default) swaps the whole list, False appends to it.

    Returns
      {ok: True, diagram_count: int}

    Errors
      validation — diagrams is not a list of {title, diagram} objects, an entry
                   has a blank title or body, an empty list was passed with
                   replace=False, or the workspace is before phase 2.0.
      business   — simple planning mode, where diagrams are not used.

    Example
      workspace_set_plan_diagrams(diagrams=[{"title": "Class Diagram",
                                             "diagram": "classDiagram\\n  A --> B"}])

    Diagrams are documentation, so plan_status is deliberately NOT reset — the
    plan stays approved and the agent keeps its permission to edit files."""
    if project["simple_planning"]:
        return _simple_mode_error("System diagrams")

    result = plan_service.set_diagrams(db, ws, diagrams, replace)
    if "error" in result:
        return _plan_error(result)
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(title="Set plan description", readOnlyHint=False, idempotentHint=True, destructiveHint=False))
@with_mcp_workspace
def workspace_set_plan_description(
    ws, project, db, locale,
    description: Annotated[str, Field(description="New high-level plain-text description of what the plan achieves.", min_length=1)],
) -> dict:
    """Replace the plan's top-level description without resubmitting the whole plan.

    Purpose
      Use this when the summary of the plan needs rewording or the goal was
      refined during execution. Diagrams and execution items are left untouched.

    Parameters
      description: New high-level plain-text description.

    Returns
      {ok: True, description: str}

    Errors
      validation — description is blank, or the workspace is before phase 2.0.

    Example
      workspace_set_plan_description(description="Add granular plan editing tools")

    The description is documentation, so plan_status is deliberately NOT reset —
    the plan stays approved and the agent keeps its permission to edit files."""
    result = plan_service.set_description(db, ws, description)
    if "error" in result:
        return _plan_error(result)
    db.commit()
    return result
