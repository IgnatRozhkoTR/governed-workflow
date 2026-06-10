"""Plan domain logic: get, set, extend operations on workspace plans.

All plan business logic lives here. MCP tools and route handlers are thin
wrappers that delegate to this module.
"""
import json
import re

from core.i18n import t
from core.phase import phase_key

_EMPTY_PLAN = {"description": "", "systemDiagram": "", "execution": []}


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


def set_plan(db, ws, plan_data):
    """Set execution plan on workspace. Resets plan_status and adjusts phase if needed.

    Every execution item must embed its own scope (must list required). Returns
    a result dict with ok/error keys.
    """
    locale = ws["locale"] or "en"
    phase = ws["phase"]

    if phase_key(phase) < phase_key("2.0"):
        return {"error": t("mcp.error.planPhase", locale)}

    scope_error = _validate_execution_scope(plan_data.get("execution", []))
    if scope_error:
        return {"error": scope_error}

    plan_json_str = json.dumps(plan_data)
    db.execute("UPDATE workspaces SET plan_json = ? WHERE id = ?", (plan_json_str, ws["id"]))
    db.execute(
        "UPDATE workspaces SET plan_status = 'pending' WHERE id = ?",
        (ws["id"],)
    )

    current_phase = ws["phase"]
    match = re.match(r'^3\.(\d+)\.\d+$', current_phase)
    if match:
        execution = plan_data.get("execution", [])
        if not execution or int(match.group(1)) > len(execution):
            new_phase = "2.0"
        else:
            new_phase = current_phase
        if new_phase != current_phase:
            db.execute("UPDATE workspaces SET phase = ? WHERE id = ?", (new_phase, ws["id"]))

    return {
        "ok": True,
        "plan_status": "pending",
        "note": t("mcp.error.planNoteRevoked", locale),
    }


def _next_subphase_id(plan):
    """Return the next available 3.N subphase number from the execution list."""
    max_n = 0
    for item in plan.get("execution", []):
        m = re.match(r'^3\.(\d+)$', item.get("id", ""))
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
    locale = ws["locale"] or "en"
    phase = ws["phase"]

    if phase_key(phase) < phase_key("2.0"):
        return {"error": t("mcp.error.planPhase", locale)}

    if not scope_entry or not isinstance(scope_entry, dict):
        return {"error": "scope is required — must be a dict with 'must' and/or 'may' patterns"}

    if not new_subphase or not isinstance(new_subphase, dict):
        return {"error": "subphase must be a dict with 'name' and 'tasks'"}

    name = new_subphase.get("name", "").strip() if isinstance(new_subphase.get("name"), str) else ""
    tasks = new_subphase.get("tasks", [])
    if not name:
        return {"error": "subphase.name is required"}
    if not tasks or not isinstance(tasks, list):
        return {"error": "subphase.tasks must be a non-empty list"}

    for i, task in enumerate(tasks):
        if not isinstance(task, dict) or not task.get("title") or not isinstance(task.get("files"), list) or not task.get("agent"):
            return {"error": f"task[{i}] must have title (string), files (list), and agent (string)"}

    if not isinstance(scope_entry.get("must"), list):
        return {"error": "scope must include a 'must' list"}

    plan = get_plan(ws)
    new_n = _next_subphase_id(plan)

    execution = plan.get("execution", [])
    execution.append({"id": f"3.{new_n}", "name": name, "scope": scope_entry, "tasks": tasks})
    plan["execution"] = execution

    if diagrams and isinstance(diagrams, list):
        _merge_diagrams(plan, diagrams, replace_diagrams)

    db.execute("UPDATE workspaces SET plan_json = ? WHERE id = ?", (json.dumps(plan), ws["id"]))
    db.execute(
        "UPDATE workspaces SET plan_status = 'pending' WHERE id = ?",
        (ws["id"],)
    )

    return {"ok": True, "new_subphase_id": f"3.{new_n}", "plan_status": "pending"}
