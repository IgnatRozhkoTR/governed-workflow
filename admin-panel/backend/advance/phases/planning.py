"""Planning workflow phase: 2.0 (plan validation and approval)."""
from advance.phases import Phase
from core.db import get_db_ctx
from core.i18n import t
from services import plan_service


class PlanningPhase(Phase):
    id = "2.0"
    name = "Planning"

    def description_for_skill(self) -> str:
        return """\
## 2.0 Planning

**Actors**: Orchestrator + plan-advisor

Message the plan-advisor teammate to collaborate on the execution plan:

```
SendMessage(
  to: "plan-advisor",
  content: "We are in the planning phase. Review the research findings and impact analysis
            via workspace_get_state. Help me design the execution plan. Consider whether this
            task needs multiple sub-phases or a single one. Each sub-phase needs: id (3.1,
            3.2, ...), name, scope (must/may globs), and tasks."
)
```

**Sub-phase count guidance**: Multiple sub-phases are NOT required. Use them only when the task naturally splits into independent, separately reviewable chunks — different layers, modules, or concerns that benefit from isolated review. For simple or atomic tasks, use a single sub-phase (just `3.1`). The purpose of sub-phases is to make the user's review manageable, not to inflate the plan. When in doubt, fewer sub-phases is better.

**Task grouping (parallel execution)**: Tasks within a sub-phase that don't conflict MUST be assigned the same `group` field so they execute in parallel. Only use sequential (different groups or no group) when tasks have real dependencies — e.g., test engineer waits for engineer to finish. The diagram renders grouped tasks as fork/join. Example:
```json
{
  "tasks": [
    {"title": "Add UserService", "agent": "middle-backend-engineer", "group": "impl"},
    {"title": "Add OrderService", "agent": "middle-backend-engineer", "group": "impl"},
    {"title": "Write UserService tests", "agent": "middle-backend-test-engineer", "group": "test"},
    {"title": "Write OrderService tests", "agent": "middle-backend-test-engineer", "group": "test"}
  ]
}
```
Here `impl` tasks run in parallel, then `test` tasks run in parallel after. Without groups, all 4 would run sequentially — wasteful when they don't conflict.

**Scope (must vs may)**: Call `workspace_set_scope` alongside the plan. The distinction matters:
- **must**: Broad areas where absence of changes means the task is incomplete. These are ticket-level requirements obvious *before* planning — e.g., if the ticket says "add BDD scenarios", the BDD module is must-scope. Keep this list short.
- **may**: Specific files and packages identified *during* planning. Most paths from the execution plan belong here. These are permitted but not required — the plan proposes them, but the user decides if they're all necessary.

When plan is agreed:
1. Call `workspace_set_scope` with must/may paths
2. Call `workspace_set_plan` with the full plan JSON
3. Call `workspace_update_progress` for phase `"2"`
4. Call `workspace_advance`

**Extending the plan later**: If during execution the user requests additional changes within the same ticket, or new work is discovered that warrants a new sub-phase, use `workspace_extend_plan` instead of rewriting the entire plan with `workspace_set_plan`. This appends a new sub-phase (auto-assigned ID, with scope) without touching existing sub-phases — fewer tokens, less risk of breaking the plan. The plan and scope statuses are set to 'pending' (user must re-approve).

**Advance 2.0 → 2.1** requires: valid plan with ≥1 execution sub-phase, plan_status='approved', scope_status='approved', ≥1 acceptance criterion, no pending/rejected criteria, and progress entry `"2"`.

---

## 2.1 Plan Review (USER GATE)

User reviews the plan, scope, and system diagram in the admin panel.

- **Approve** → advances to `3.1.0`
- **Reject** → back to `2.0` with comments

Poll `workspace_get_state` once per minute. After 10 polls, ask user in chat.

**After rejection**: the backend sets the phase to `2.0`. Do NOT call `workspace_advance` immediately. Instead:
1. Call `workspace_get_state` to confirm you're at `2.0`
2. Call `workspace_get_comments` to read the rejection feedback
3. Message plan-advisor via `SendMessage(to: "plan-advisor", ...)` with the feedback to revise the plan
4. Call `workspace_set_plan` and `workspace_set_scope` with the revised plan
5. Call `workspace_advance` only after the plan is updated"""

    def progress_key(self, ws):
        return "2"

    def validate(self, ws, body, project_path):
        locale = ws["locale"]

        if ws["scope_status"] != "approved" or ws["plan_status"] != "approved":
            return False, {"error": t("advance.error.scopeAndPlanMustBeApproved", locale)}

        plan = plan_service.get_plan(ws)
        execution = plan.get("execution", [])

        if not execution:
            return False, {"message": t("advance.error.noPlanExecution", locale)}

        issues = []
        expected_index = 1
        for i, item in enumerate(execution):
            item_id = item.get("id", "")
            expected_id = f"3.{expected_index}"
            if item_id != expected_id:
                issues.append(t("advance.error.planItemIdMismatch", locale, i=i, expected_id=expected_id, actual_id=item_id))

            if not isinstance(item.get("name"), str) or not item.get("name"):
                issues.append(t("advance.error.planItemMissingName", locale, i=i))

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

        if issues:
            return False, {"message": t("advance.error.planValidationFailed", locale), "issues": issues}

        with get_db_ctx() as db:
            count = db.execute(
                "SELECT COUNT(*) as cnt FROM acceptance_criteria WHERE workspace_id = ?",
                (ws["id"],)
            ).fetchone()["cnt"]
            pending = db.execute(
                "SELECT COUNT(*) as cnt FROM acceptance_criteria "
                "WHERE workspace_id = ? AND status IN ('proposed', 'rejected')",
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
