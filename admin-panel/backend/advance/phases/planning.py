"""Planning workflow phase: 2.0 (plan validation and approval)."""
from advance.phases import Phase
from core.db import get_db_ctx
from core.i18n import t
from services import plan_service


class PlanningPhase(Phase):
    id = "2.0"
    name = "Planning"
    short_description = "Orchestrator and plan-advisor draft the execution plan and scope"

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

**Scope (must vs may)**: Scope is part of the plan — each execution item carries its own `scope: {must, may}`. The distinction matters:
- **must**: Broad areas where absence of changes means the task is incomplete. These are ticket-level requirements obvious *before* planning — e.g., if the ticket says "add BDD scenarios", the BDD module is must-scope. Keep this list short.
- **may**: Specific files and packages identified *during* planning. Most paths from the execution plan belong here. These are permitted but not required — the plan proposes them, but the user decides if they're all necessary.

When plan is agreed:
1. Call `workspace_set_plan` with the full plan JSON — each execution item must include its `scope` (must/may)
2. Propose acceptance criteria via `workspace_propose_criteria` (unit tests, integration tests, BDD scenarios, custom checks). At least one criterion is required before advancing.
3. Call `workspace_update_progress` for phase `"2"`
4. Call `workspace_advance`

**Extending the plan later**: If during execution the user requests additional changes within the same ticket, or new work is discovered that warrants a new sub-phase, use `workspace_extend_plan` instead of rewriting the entire plan with `workspace_set_plan`. This appends a new sub-phase (auto-assigned ID, with its own scope) without touching existing sub-phases — fewer tokens, less risk of breaking the plan. The plan status is set to 'pending' (user must re-approve).

**User review (happens while the workspace sits at 2.0)**: The user reviews and approves the plan in the admin panel. Approving the plan also approves its scope and accepts all proposed acceptance criteria — it is the single approval. `workspace_advance` stays blocked until `plan_status='approved'`. On approval, advancing from 2.0 moves the workspace directly to `3.1.0` (the first execution item) — there is no separate 2.1 gate phase. If the user rejects, the plan status goes back to pending/rejected; revise the plan with plan-advisor and resubmit via `workspace_set_plan`, then call `workspace_advance` again.

**Advance 2.0 → 3.1.0** requires: valid plan with ≥1 execution sub-phase (each with a non-empty `scope.must`), plan_status='approved', ≥1 acceptance criterion, no proposed criteria, and progress entry `"2"`."""

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

        if issues:
            return False, {"message": t("advance.error.planValidationFailed", locale), "issues": issues}

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
