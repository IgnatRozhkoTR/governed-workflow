"""Finalization workflow phases: 4.0 (agentic review) through 5 (done)."""
from advance.phases import Phase
from core.i18n import t


class AgenticReviewPhase(Phase):
    id = "4.0"
    name = "Agentic Review"

    def description_for_skill(self) -> str:
        return """\
## 4.0 Blind Code Review (automated)

**Actors**: Headless review pipeline (background daemon) | **Code edits: OFF**

On entry to 4.0 the admin panel **automatically launches** the headless review pipeline. Per-file reviewers fan out in parallel across the diff, then two specialised integration reviewers run concurrently:

- **architecture-reviewer** — SRP/OCP, coupling, layer boundaries, clean-code principles, naming, method/class size, DRY
- **correctness-reviewer** — business-logic correctness, edge cases, error handling, security (input validation, injection, auth/authz, secrets, sensitive data in logs, API contract leaks)

**Do NOT manually dispatch reviewers.** The pipeline is already running. Manual dispatch would duplicate work and confuse findings.

### What you do at 4.0

1. Watch the **Review Pipeline** card on the workspace page in the admin panel, or poll `GET /api/workspaces/<id>/review-pipeline-status`. States: `queued` → `filtering` → `file_stage` → `integration_stage` → `done` (or `failed`).
2. When state is `done` or `failed`:
   - Call `workspace_get_review_issues` to see the findings.
   - Call `workspace_update_progress(phase="4.0", summary="Pipeline complete. N findings.")`.
   - Before calling `workspace_advance`, call `workspace_review_pipeline_summary` (or `GET /api/workspaces/<id>/review-pipeline/summary`). Confirm `is_complete=true` and `is_ok=true`. If `files_failed > 0` or `integration_failed > 0`, decide: re-trigger via the Run Review button (workspace page) or `POST /api/workspaces/<id>/review-pipeline/start`, OR proceed with the partial result if the failures are recoverable.
   - Call `workspace_advance` to move to 4.1.

If the pipeline failed mid-run, the reason is exposed only via `workspace_review_pipeline_summary` (`failed_files_errors`, `integration_errors`, top-level `error`) — never as a discussion. Inspect those fields and decide whether to re-trigger or proceed.

**Advance 4.0 → 4.1** requires: progress entry for phase `"4.0"`."""

    def progress_key(self, ws):
        return "4.0"

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return "4.1"


class AddressFixPhase(Phase):
    id = "4.1"
    name = "Address Fix"

    def description_for_skill(self) -> str:
        return """\
## 4.1 Address & Fix

**Actors**: Engineer sub-agents | **Code edits: ON (merged scope), Commits: ON**

Active scope = union of all sub-phase scopes.

1. Read review items via `workspace_get_review_issues`. Findings from the headless pipeline are tagged in their description: `[severity/type]` for per-file findings, `[integration:agent-name]` for integration-reviewer findings. Use the tags to triage by lane.
2. Address each finding — fix the code, or determine it's a false positive / out of scope
3. Set resolution via `workspace_resolve_review_issue(issue_id, "fixed"|"false_positive"|"out_of_scope")`
4. The user reviews resolutions in the admin panel and resolves each item

**Important**: Agents set the `resolution` but cannot resolve items. Only the user can resolve review items (set `status='resolved'`) via the admin panel. The `ReviewGuard` blocks advancement until ALL scope='review' discussions are user-resolved.

When complete:
1. Call `workspace_update_progress` for phase `"4"`
2. Call `workspace_advance`

**Advance 4.1 → 4.2** requires: progress entry `"4"` + all review items resolved by user."""

    def progress_key(self, ws):
        return "4"

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return "4.2"


class FinalApprovalPhase(Phase):
    id = "4.2"
    name = "Final Approval"
    is_user_gate = True
    approve_target = "5"
    reject_target = "4.1"

    def description_for_skill(self) -> str:
        return """\
## 4.2 Final Approval (USER GATE)

- **Approve** → `5`
- **Reject** → back to `4.1`

Poll `workspace_get_state` once per minute. After 10 polls, ask user in chat.

**After rejection**: the backend sets the phase to `4.1`. Do NOT call `workspace_advance` immediately. Instead:
1. Call `workspace_get_state` to confirm you're at `4.1`
2. Call `workspace_get_comments` to read the rejection feedback
3. Address the feedback — fix code, update resolutions
4. Call `workspace_advance` only after fixes are complete"""

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return "5"


class DonePhase(Phase):
    id = "5"
    name = "Done"

    def description_for_skill(self) -> str:
        return """\
## 5 Done

Push and MR/PR creation allowed. Task complete."""

    def validate(self, ws, body, project_path):
        locale = ws["locale"]
        return False, {"error": t("phase.done.complete", locale)}

    def next_phase(self, ws):
        return "5"


PHASES = [AgenticReviewPhase(), AddressFixPhase(), FinalApprovalPhase(), DonePhase()]
