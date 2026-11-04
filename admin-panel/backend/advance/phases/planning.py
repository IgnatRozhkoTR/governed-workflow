"""Planning workflow phase: 2.0 (plan validation and approval)."""
import sqlite3

from advance.phases import Phase
from core.db import get_db_ctx, ws_field
from core.i18n import t
from services import plan_service


def _is_simple_planning(db: sqlite3.Connection, project_id: str) -> bool:
    """Return the simple_planning flag for the given project."""
    row = db.execute(
        "SELECT simple_planning FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return bool(row["simple_planning"]) if row else False


class PlanningPhase(Phase):
    id = "2.0"
    name = "Planning"
    short_description = "Orchestrator and plan-advisor draft the execution plan and scope"

    def description_for_skill(self, simple_planning: bool = False, workflow_mode: str = "standard") -> str:
        if simple_planning:
            return self._simple_description()
        if workflow_mode == "fast":
            return self._fast_description()
        return self._full_description()

    def _fast_description(self) -> str:
        return """\
## 2.0 Planning

**Actors**: Orchestrator + plan-advisor

Fast mode: the plan MUST have exactly ONE execution sub-phase (`3.1`) covering the whole change — no additional sub-phases.

Message the plan-advisor teammate to collaborate on the execution plan:

```
SendMessage(
  to: "plan-advisor",
  content: "We are in the planning phase. Review the research findings via workspace_get_state.
            Help me design the execution plan for this task. We need exactly ONE sub-phase (3.1)
            with its scope and tasks."
)
```

When the plan is agreed:
1. Call `workspace_set_plan` with the full plan JSON — exactly ONE execution item with `"id": "3.1"`:
```json
{
  "description": "High-level description of what this plan achieves",
  "systemDiagram": [],
  "execution": [
    {
      "id": "3.1",
      "name": "Sub-phase name",
      "scope": {"must": ["src/models/"], "may": ["src/config/"]},
      "tasks": [{"title": "...", "files": ["..."], "agent": "..."}]
    }
  ]
}
```
2. Acceptance criteria are optional in fast mode — propose any via `workspace_propose_criteria` if useful, but none are required to advance.
3. Call `workspace_update_progress` for phase `"2"`
4. Call `workspace_advance`

**Editing the plan later**: do not resubmit the whole plan to change one part of it. Use `workspace_update_subphase` to patch `3.1`'s name, tasks or scope (sets plan status to 'pending' — the user must re-approve), and `workspace_set_plan_diagrams` / `workspace_set_plan_description` for documentation edits (these keep the approval intact). Fast mode stays at one sub-phase, so `workspace_extend_plan` and `workspace_delete_subphase` do not apply.

**User review (happens while the workspace sits at 2.0)**: The user reviews and approves the plan in the admin panel (auto-approved when `yolo_mode` is on). `workspace_advance` is refused until then — after submitting the plan, tell the user it awaits approval and end the turn; do not poll. When the user messages or a scheduled check fires, check `workspace_get_state` once and advance if `plan_status='approved'`. On approval, advancing from 2.0 moves the workspace directly into the first execution item.

**Advancing from 2.0** requires: a single execution sub-phase `3.1` with a non-empty `scope.must`, plan_status='approved', and progress entry `"2"`."""

    def _simple_description(self) -> str:
        return """\
## 2.0 Planning

**Actors**: Orchestrator + plan-advisor

Message the plan-advisor teammate to collaborate on the execution plan:

```
SendMessage(
  to: "plan-advisor",
  content: "We are in the planning phase. Review the research findings and impact analysis
            via workspace_get_state. Help me design the execution plan for this task.
            We need exactly ONE sub-phase (3.1) with its scope and tasks."
)
```

When the plan is agreed:
1. Call `workspace_set_plan` with the full plan JSON — exactly ONE execution item with `"id": "3.1"`:
```json
{
  "description": "High-level description of what this plan achieves",
  "systemDiagram": [],
  "execution": [
    {
      "id": "3.1",
      "name": "Sub-phase name",
      "scope": {"must": ["src/models/"], "may": ["src/config/"]},
      "tasks": [{"title": "...", "files": ["..."], "agent": "..."}]
    }
  ]
}
```
2. Call `workspace_update_progress` for phase `"2"`
3. Call `workspace_advance`

**Editing the plan later**: to reword the plan's summary, call `workspace_set_plan_description` instead of resubmitting the whole plan — it keeps the user's approval intact.

**User review (happens while the workspace sits at 2.0)**: The user reviews and approves the plan in the admin panel. `workspace_advance` is refused until then — after submitting the plan, tell the user it awaits approval and end the turn; do not poll. When the user messages or a scheduled check fires, check `workspace_get_state` once and advance if `plan_status='approved'`. On approval, advancing from 2.0 moves the workspace directly into the first execution item.

**Advancing from 2.0** requires: a single execution sub-phase `3.1` with a non-empty `scope.must`, plan_status='approved', and progress entry `"2"`."""

    def _full_description(self) -> str:
        return """\
## 2.0 Planning

**Actors**: Orchestrator + plan-advisor

Follow `/planning`: plan structure, sub-phase split rules, task grouping, must/may scope, the structured plan-advisor brief, acceptance-criteria rules, and the granular plan-editing tools.

When plan is agreed:
1. Call `workspace_set_plan` with the full plan JSON — each execution item must include its `scope` (must/may)
2. Propose acceptance criteria via `workspace_propose_criteria` (unit tests, integration tests, BDD scenarios, custom checks). At least one criterion is required before advancing.
3. Call `workspace_update_progress` for phase `"2"`
4. Call `workspace_advance`

**Editing the plan later**: never resubmit the whole plan to change one part of it. Use `workspace_extend_plan` to append a sub-phase, and the other granular tools listed in `/planning` for in-place edits.

**User review (happens while the workspace sits at 2.0)**: The user reviews and approves the plan in the admin panel. Approving the plan also approves its scope and accepts all proposed acceptance criteria — it is the single approval. `workspace_advance` is refused until then — after submitting the plan, tell the user it awaits approval and end the turn; do not poll. When the user messages or a scheduled check fires, check `workspace_get_state` once and advance if `plan_status='approved'`. On approval, advancing from 2.0 moves the workspace directly into the first execution item — there is no separate gate phase between planning and execution. If the user rejects, the plan status goes back to pending/rejected; revise the plan with plan-advisor and resubmit via `workspace_set_plan`, then call `workspace_advance` again.

**Advancing from 2.0** requires: valid plan with ≥1 execution sub-phase (each with a non-empty `scope.must`), plan_status='approved', ≥1 acceptance criterion, no proposed criteria, and progress entry `"2"`."""

    def progress_key(self, ws):
        return "2"

    def validate(self, ws, body, project_path):
        locale = ws["locale"]

        if ws["plan_status"] != "approved":
            return False, {"error": t("advance.error.planMustBeApproved", locale)}

        plan = plan_service.get_plan(ws)
        execution = plan.get("execution", [])

        if not execution:
            return False, {"message": t("advance.error.noPlanExecution", locale)}

        with get_db_ctx() as db:
            is_simple = _is_simple_planning(db, ws["project_id"])
        is_fast = ws_field(ws, "workflow_mode", "standard") == "fast"

        if (is_simple or is_fast) and plan_service.exceeds_single_execution_item(execution):
            mode_label = "Simple planning" if is_simple else "Fast workflow"
            return False, {"message": f"{mode_label} mode requires exactly one execution sub-phase."}

        issues = self._validate_execution_items(execution, locale)
        if issues:
            return False, {"message": t("advance.error.planValidationFailed", locale), "issues": issues}

        if not (is_simple or is_fast):
            ok, detail = self._validate_criteria(ws, locale)
            if not ok:
                return False, detail

        return True, {}

    def _validate_execution_items(self, execution: list, locale: str) -> list:
        issues = []
        expected_index = 1
        for i, item in enumerate(execution):
            item_id = item.get("id", "")
            expected_id = f"3.{expected_index}"
            if item_id != expected_id:
                issues.append(t("advance.error.planItemIdMismatch", locale, i=i, expected_id=expected_id, actual_id=item_id))

            if not isinstance(item.get("name"), str) or not item.get("name"):
                issues.append(t("advance.error.planItemMissingName", locale, i=i))

            scope = item.get("scope")
            if not isinstance(scope, dict) or not isinstance(scope.get("must"), list):
                issues.append(t("advance.error.planItemMissingScope", locale, i=i))

            tasks = item.get("tasks", [])
            if not isinstance(tasks, list) or not tasks:
                issues.append(t("advance.error.planItemTasksMustBeArray", locale, i=i))
            else:
                for ti, task in enumerate(tasks):
                    if not isinstance(task.get("title"), str) or not task.get("title"):
                        issues.append(t("advance.error.planTaskMissingTitle", locale, i=i, ti=ti))
                    if not isinstance(task.get("files"), list):
                        issues.append(t("advance.error.planTaskFilesMustBeArray", locale, i=i, ti=ti))
                    if not isinstance(task.get("agent"), str) or not task.get("agent"):
                        issues.append(t("advance.error.planTaskMissingAgent", locale, i=i, ti=ti))

            expected_index += 1
        return issues

    def _validate_criteria(self, ws, locale: str) -> tuple:
        with get_db_ctx() as db:
            count = db.execute(
                "SELECT COUNT(*) as cnt FROM acceptance_criteria WHERE workspace_id = ?",
                (ws["id"],)
            ).fetchone()["cnt"]
            pending = db.execute(
                "SELECT COUNT(*) as cnt FROM acceptance_criteria "
                "WHERE workspace_id = ? AND status = 'proposed'",
                (ws["id"],)
            ).fetchone()["cnt"]

        if count == 0:
            return False, {"message": t("advance.error.noCriteria", locale)}
        if pending > 0:
            return False, {"error": t("gate.error.pendingCriteria", locale, count=pending)}
        return True, {}

    def next_phase(self, ws):
        plan = plan_service.get_plan(ws)
        execution = plan.get("execution", [])
        return execution[0]["id"] + ".0"

    def success_message(self, ws, new_phase):
        locale = ws["locale"]
        plan = plan_service.get_plan(ws)
        execution = plan.get("execution", [])
        return t("advance.success.planValidated", locale, count=len(execution))


PHASES = [PlanningPhase()]
