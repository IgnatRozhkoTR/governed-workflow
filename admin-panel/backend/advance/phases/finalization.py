"""Finalization workflow phases: 4.0 (agentic review) through 5 (done)."""
from advance.phases import Phase
from core.i18n import t


class AgenticReviewPhase(Phase):
    id = "4.0"
    name = "Agentic Review"

    def description_for_skill(self) -> str:
        return """\
## 4.0 Blind Code Review

**Actors**: Fresh reviewer sub-agents (zero implementation context) | **Code edits: OFF**

Deploy **exactly 3** code-reviewer sub-agents **in parallel**, each assigned a distinct review perspective:

1. **Clean code & SOLID** — naming, method length, SRP violations, DRY, code smells
2. **Architecture & data flow** — component boundaries, dependency direction, query patterns, transaction scope
3. **Edge cases & error handling** — null paths, missing validation, error propagation, concurrency concerns

Do NOT brief reviewers with implementation context — they must review the code blind. Provide only the ticket description and branch name.

Reviewers submit findings via `workspace_submit_review_issue(file_path, line_start, line_end, severity, description)`. Only `critical` and `major` severity findings are accepted — lower severity is rejected by the server.

Each submitted finding creates a review discussion with `resolution='open'`.

Call `workspace_advance`.

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

1. Read review items via `workspace_get_review_issues`
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
