from typing import Annotated, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import mcp, mcp_error, with_mcp_workspace
from services import plan_service


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
    scope: must/may scope entry for the new sub-phase; embedded into the new
      execution item. A 'must' list is required.
    diagrams: optional list of {title, diagram} objects to add. Appended by default;
      set replace_diagrams=True to replace the entire diagram list instead.

    plan_status is set to 'pending'. Existing sub-phases are unchanged."""
    result = plan_service.extend_plan(db, ws, subphase, scope, diagrams, replace_diagrams)
    if "error" in result:
        return mcp_error("validation", result["error"], retryable=False)
    db.commit()
    return result
