"""Plan domain logic: get, set, extend and granular edit operations on workspace plans.

All plan business logic lives here. MCP tools and route handlers are thin
wrappers that delegate to this module.
"""
import json
import re

from core.i18n import t
from core.phase import phase_key

_EMPTY_PLAN = {"description": "", "systemDiagram": "", "execution": []}

_SUBPHASE_ID = re.compile(r'^3\.(\d+)$')
_EXECUTION_PHASE = re.compile(r'^3\.(\d+)\.\d+$')
_REPLANNING_PHASE = "2.0"


def get_plan(ws):
    """Parse plan_json from workspace row with default fallback."""
    raw = ws["plan_json"]
    if raw:
        return json.loads(raw)
    return dict(_EMPTY_PLAN)


def get_scope(ws):
    """Reconstruct the phase-keyed scope map {"3.N": {must, may}} from the plan.

    Scope now lives inside each plan execution item under a "scope" key. This
    rebuilds the legacy phase-keyed shape so callers that still expect a
    sub-phase-keyed map (state serialization, reflection, panel) keep working.
    """
    plan = get_plan(ws)
    scope_map = {}
    for item in plan.get("execution", []):
        item_id = item.get("id")
        item_scope = item.get("scope")
        if item_id and isinstance(item_scope, dict):
            scope_map[item_id] = item_scope
    return scope_map


def _validate_execution_scope(execution):
    """Return an error string when any execution item lacks a valid scope.must.

    Scope is embedded per execution item now; every item must carry a scope
    object with a "must" list (the "may" list is optional).
    """
    for i, item in enumerate(execution):
        scope = item.get("scope")
        if not isinstance(scope, dict):
            return f"execution[{i}] is missing a 'scope' object with a 'must' list"
        if not isinstance(scope.get("must"), list):
            return f"execution[{i}].scope must include a 'must' list"
    return None


def _validate_subphase_name(name):
    """Return an error string when a sub-phase name is missing or blank."""
    if not isinstance(name, str) or not name.strip():
        return "subphase.name is required"
    return None


def _validate_subphase_tasks(tasks):
    """Return an error string when the task list is empty or a task lacks required fields."""
    if not tasks or not isinstance(tasks, list):
        return "subphase.tasks must be a non-empty list"
    for i, task in enumerate(tasks):
        if (not isinstance(task, dict) or not task.get("title")
                or not isinstance(task.get("files"), list) or not task.get("agent")):
            return f"task[{i}] must have title (string), files (list), and agent (string)"
    return None


def _validate_scope_entry(scope_entry):
    """Return an error string when a sub-phase scope is missing or lacks a 'must' list."""
    if not scope_entry or not isinstance(scope_entry, dict):
        return "scope is required — must be a dict with 'must' and/or 'may' patterns"
    if not isinstance(scope_entry.get("must"), list):
        return "scope must include a 'must' list"
    return None


def _validate_diagram_entries(diagrams):
    """Return an error string when diagrams is not a list of {title, diagram} objects."""
    if not isinstance(diagrams, list):
        return "diagrams must be a list of {title, diagram} objects"
    for i, entry in enumerate(diagrams):
        if not isinstance(entry, dict):
            return f"diagrams[{i}] must be an object with 'title' and 'diagram' strings"
        if not isinstance(entry.get("title"), str) or not entry["title"].strip():
            return f"diagrams[{i}].title must be a non-empty string"
        if not isinstance(entry.get("diagram"), str) or not entry["diagram"].strip():
            return f"diagrams[{i}].diagram must be a non-empty Mermaid string"
    return None


def _planning_phase_error(ws):
    """Return an error dict when the workspace has not reached the planning phase yet."""
    if phase_key(ws["phase"]) < phase_key(_REPLANNING_PHASE):
        return {"error": t("mcp.error.planPhase", ws["locale"] or "en")}
    return None


def _write_plan(db, ws, plan, revoke_approval: bool):
    """Persist the plan JSON, optionally revoking the user's approval.

    Only structural edits revoke approval: a pending plan_status also revokes the
    agent's permission to write files, so description and diagram edits — which
    change nothing the user approved — deliberately leave the status alone.
    """
    db.execute("UPDATE workspaces SET plan_json = ? WHERE id = ?", (json.dumps(plan), ws["id"]))
    if revoke_approval:
        db.execute("UPDATE workspaces SET plan_status = 'pending' WHERE id = ?", (ws["id"],))


def _rewind_phase_when_subphase_missing(db, ws, execution):
    """Send the workspace back to planning when its current 3.N sub-phase no longer exists.

    Returns the phase the workspace is left on.
    """
    current_phase = ws["phase"]
    match = _EXECUTION_PHASE.match(current_phase)
    if not match:
        return current_phase
    if execution and int(match.group(1)) <= len(execution):
        return current_phase
    db.execute("UPDATE workspaces SET phase = ? WHERE id = ?", (_REPLANNING_PHASE, ws["id"]))
    return _REPLANNING_PHASE


def _find_subphase_index(execution, subphase_id):
    """Return the position of subphase_id in the execution list, or None when absent."""
    for index, item in enumerate(execution):
        if item.get("id") == subphase_id:
            return index
    return None


def exceeds_single_execution_item(execution: list) -> bool:
    """True when execution has more than one item.

    Shared between set_plan (submission time) and PlanningPhase.validate
    (advance-gate time): both simple_planning and fast workflow_mode collapse
    the plan to exactly one execution sub-phase, so both call this instead of
    duplicating the length check.
    """
    return len(execution) > 1


def set_plan(db, ws, plan_data, simple_mode: bool = False, fast_mode: bool = False):
    """Set execution plan on workspace. Resets plan_status and adjusts phase if needed.

    Every execution item must embed its own scope (must list required). When
    simple_mode is True, the plan must contain exactly one execution item and
    no system diagrams. When fast_mode is True (and simple_mode is False), the
    plan must contain exactly one execution item; diagrams are unrestricted.
    Returns a result dict with ok/error keys.
    """
    locale = ws["locale"] or "en"

    phase_error = _planning_phase_error(ws)
    if phase_error:
        return phase_error

    if simple_mode:
        if exceeds_single_execution_item(plan_data.get("execution", [])):
            return {
                "error": "Simple planning mode allows exactly one execution sub-phase (3.1).",
                "errorCode": "simple_multiple_subphases",
            }
        diagram = plan_data.get("systemDiagram")
        if diagram and diagram != [] and diagram != "":
            return {
                "error": "System diagrams are not used in simple planning mode.",
                "errorCode": "simple_no_diagrams",
            }
    elif fast_mode:
        if exceeds_single_execution_item(plan_data.get("execution", [])):
            return {
                "error": "Fast workflow mode allows exactly one execution sub-phase (3.1).",
                "errorCode": "fast_multiple_subphases",
            }

    scope_error = _validate_execution_scope(plan_data.get("execution", []))
    if scope_error:
        return {"error": scope_error}

    _write_plan(db, ws, plan_data, revoke_approval=True)
    _rewind_phase_when_subphase_missing(db, ws, plan_data.get("execution", []))

    return {
        "ok": True,
        "plan_status": "pending",
        "note": t("mcp.error.planNoteRevoked", locale),
    }


def _next_subphase_id(plan):
    """Return the next available 3.N subphase number from the execution list."""
    max_n = 0
    for item in plan.get("execution", []):
        m = _SUBPHASE_ID.match(item.get("id", ""))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _merge_diagrams(plan, new_diagrams, replace):
    """Merge new_diagrams into plan's systemDiagram in-place."""
    if replace:
        plan["systemDiagram"] = new_diagrams
    else:
        existing = plan.get("systemDiagram", [])
        if isinstance(existing, str):
            existing = [{"title": "", "diagram": existing}] if existing else []
        plan["systemDiagram"] = existing + new_diagrams


def extend_plan(db, ws, new_subphase, scope_entry, diagrams=None, replace_diagrams=False):
    """Append a new sub-phase to the execution plan without rewriting existing sub-phases.

    Returns a result dict with ok/error keys and the new subphase ID.
    """
    phase_error = _planning_phase_error(ws)
    if phase_error:
        return phase_error

    if not scope_entry or not isinstance(scope_entry, dict):
        return {"error": "scope is required — must be a dict with 'must' and/or 'may' patterns"}

    if not new_subphase or not isinstance(new_subphase, dict):
        return {"error": "subphase must be a dict with 'name' and 'tasks'"}

    name = new_subphase.get("name")
    tasks = new_subphase.get("tasks", [])
    for error in (_validate_subphase_name(name), _validate_subphase_tasks(tasks),
                  _validate_scope_entry(scope_entry)):
        if error:
            return {"error": error}
    name = name.strip()

    plan = get_plan(ws)
    new_n = _next_subphase_id(plan)

    execution = plan.get("execution", [])
    execution.append({"id": f"3.{new_n}", "name": name, "scope": scope_entry, "tasks": tasks})
    plan["execution"] = execution

    if diagrams and isinstance(diagrams, list):
        _merge_diagrams(plan, diagrams, replace_diagrams)

    _write_plan(db, ws, plan, revoke_approval=True)

    return {"ok": True, "new_subphase_id": f"3.{new_n}", "plan_status": "pending"}


def _build_subphase_patch(name, tasks, scope):
    """Validate the supplied fields and return (patch_dict, error_dict_or_None)."""
    patch = {}
    if name is not None:
        error = _validate_subphase_name(name)
        if error:
            return {}, {"error": error}
        patch["name"] = name.strip()
    if tasks is not None:
        error = _validate_subphase_tasks(tasks)
        if error:
            return {}, {"error": error}
        patch["tasks"] = tasks
    if scope is not None:
        error = _validate_scope_entry(scope)
        if error:
            return {}, {"error": error}
        patch["scope"] = scope
    if not patch:
        return {}, {
            "error": "Nothing to update — provide name, tasks and/or scope.",
            "errorCode": "nothing_to_update",
        }
    return patch, None


def update_subphase(db, ws, subphase_id, name=None, tasks=None, scope=None):
    """Patch one existing execution item in place, leaving the others untouched.

    Only the arguments that are not None are applied. Structural change, so the
    plan approval is revoked. Returns a result dict with ok/error keys.
    """
    phase_error = _planning_phase_error(ws)
    if phase_error:
        return phase_error

    plan = get_plan(ws)
    execution = plan.get("execution", [])
    index = _find_subphase_index(execution, subphase_id)
    if index is None:
        return {
            "error": f"Sub-phase '{subphase_id}' is not in the plan.",
            "errorCode": "subphase_not_found",
        }

    patch, error = _build_subphase_patch(name, tasks, scope)
    if error:
        return error

    execution[index] = {**execution[index], **patch}
    plan["execution"] = execution
    _write_plan(db, ws, plan, revoke_approval=True)

    return {"ok": True, "subphase": execution[index], "plan_status": "pending"}


def _renumbered(execution):
    """Reassign sequential 3.N ids to execution items, preserving their order."""
    return [{**item, "id": f"3.{position}"} for position, item in enumerate(execution, start=1)]


def delete_subphase(db, ws, subphase_id):
    """Remove one execution item and renumber the remaining ones to stay sequential.

    A plan must keep at least one sub-phase. When the workspace was sitting on a
    sub-phase that no longer exists it is rewound to planning. Structural change,
    so the plan approval is revoked. Returns a result dict with ok/error keys.
    """
    phase_error = _planning_phase_error(ws)
    if phase_error:
        return phase_error

    plan = get_plan(ws)
    execution = plan.get("execution", [])
    index = _find_subphase_index(execution, subphase_id)
    if index is None:
        return {
            "error": f"Sub-phase '{subphase_id}' is not in the plan.",
            "errorCode": "subphase_not_found",
        }
    if len(execution) == 1:
        return {
            "error": "A plan must keep at least one execution sub-phase.",
            "errorCode": "cannot_delete_last_subphase",
        }

    del execution[index]
    plan["execution"] = _renumbered(execution)
    _write_plan(db, ws, plan, revoke_approval=True)
    phase = _rewind_phase_when_subphase_missing(db, ws, plan["execution"])

    return {
        "ok": True,
        "deleted_id": subphase_id,
        "execution_ids": [item["id"] for item in plan["execution"]],
        "phase": phase,
        "plan_status": "pending",
    }


def set_diagrams(db, ws, diagrams, replace=True):
    """Replace or append the plan's top-level systemDiagram entries.

    Diagrams are documentation, so the plan approval is left untouched.
    Returns a result dict with ok/error keys.
    """
    phase_error = _planning_phase_error(ws)
    if phase_error:
        return phase_error

    error = _validate_diagram_entries(diagrams)
    if error:
        return {"error": error}
    if not diagrams and not replace:
        return {"error": "diagrams must contain at least one entry when appending"}

    plan = get_plan(ws)
    _merge_diagrams(plan, diagrams, replace)
    _write_plan(db, ws, plan, revoke_approval=False)

    return {"ok": True, "diagram_count": len(plan["systemDiagram"])}


def set_description(db, ws, description):
    """Replace the plan's top-level description.

    The description is documentation, so the plan approval is left untouched.
    Returns a result dict with ok/error keys.
    """
    phase_error = _planning_phase_error(ws)
    if phase_error:
        return phase_error

    if not isinstance(description, str) or not description.strip():
        return {"error": "description must be a non-empty string"}

    plan = get_plan(ws)
    plan["description"] = description.strip()
    _write_plan(db, ws, plan, revoke_approval=False)

    return {"ok": True, "description": plan["description"]}
