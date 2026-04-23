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
    """Parse scope_json from workspace row with default fallback."""
    raw = ws["scope_json"]
    if raw:
        return json.loads(raw)
    return {}


def set_plan(db, ws, plan_data):
    """Set execution plan on workspace. Resets statuses and adjusts phase if needed.

    Returns a result dict with ok/error keys.
    """
    locale = ws["locale"] or "en"
    phase = ws["phase"]

    if phase_key(phase) < phase_key("2.0"):
        return {"error": t("mcp.error.planPhase", locale)}

    plan_json_str = json.dumps(plan_data)
    db.execute("UPDATE workspaces SET plan_json = ? WHERE id = ?", (plan_json_str, ws["id"]))
    db.execute(
        "UPDATE workspaces SET plan_status = 'pending', scope_status = 'pending' WHERE id = ?",
        (ws["id"],)
    )

    current_phase = ws["phase"]
    match = re.match(r'^3\.(\d+)\.\d+$', current_phase)
    if match:
        execution = plan_data.get("execution", [])
        if not execution:
            new_phase = "2.0"
        elif int(match.group(1)) > len(execution):
            new_phase = "3.0"
        else:
            new_phase = current_phase
        if new_phase != current_phase:
            db.execute("UPDATE workspaces SET phase = ? WHERE id = ?", (new_phase, ws["id"]))

    return {
        "ok": True,
        "plan_status": "pending",
        "scope_status": "pending",
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

    plan = get_plan(ws)
    new_n = _next_subphase_id(plan)

    execution = plan.get("execution", [])
    execution.append({"id": f"3.{new_n}", "name": name, "tasks": tasks})
    plan["execution"] = execution

    if diagrams and isinstance(diagrams, list):
        _merge_diagrams(plan, diagrams, replace_diagrams)

    db.execute("UPDATE workspaces SET plan_json = ? WHERE id = ?", (json.dumps(plan), ws["id"]))

    scope_map = get_scope(ws)
    scope_map[f"3.{new_n}"] = scope_entry
    db.execute("UPDATE workspaces SET scope_json = ? WHERE id = ?", (json.dumps(scope_map), ws["id"]))

    db.execute(
        "UPDATE workspaces SET plan_status = 'pending', scope_status = 'pending' WHERE id = ?",
        (ws["id"],)
    )

    return {"ok": True, "new_subphase_id": f"3.{new_n}", "plan_status": "pending", "scope_status": "pending"}
