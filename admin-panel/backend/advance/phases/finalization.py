"""Finalization workflow phases: 4.0 (agentic review) through 6 (done)."""
from advance.phases import Phase
from core.db import get_db_ctx
from core.i18n import t
from services.proposal_service import count_pending_manual_proposals


class AgenticReviewPhase(Phase):
    id = "4.0"
    name = "Agentic Review"
    short_description = "Headless review pipeline runs file and integration reviewers"

    def description_for_skill(self, simple_planning: bool = False) -> str:
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
    short_description = "Engineers address review findings across the merged scope"

    def description_for_skill(self, simple_planning: bool = False) -> str:
        return """\
## 4.1 Address & Fix

**Actors**: Engineer sub-agents | **Code edits: ON (merged scope), Commits: ON**

Active scope = union of all sub-phase scopes.

1. Read review items via `workspace_get_review_issues`. Findings from the headless pipeline are tagged in their description: `[severity/type]` for per-file findings, `[integration:agent-name]` for integration-reviewer findings. Use the tags to triage by lane.
2. Address each finding — fix the code, or determine it's a false positive / out of scope
3. Set resolution via `workspace_resolve_review_issue(issue_id, "fixed"|"false_positive"|"out_of_scope")`
4. After marking resolutions, spawn the `review-validator` sub-agent to verify that `fixed` issues were actually fixed and `false_positive` claims hold. If it disagrees, it reopens or re-resolves the item via MCP — address its findings before proceeding.
5. The user reviews resolutions in the admin panel and resolves each item

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
    approve_target = "5.1"
    reject_target = "4.1"
    short_description = "User reviews the resolved findings and approves delivery"

    def description_for_skill(self, simple_planning: bool = False) -> str:
        return """\
## 4.2 Final Approval (USER GATE)

- **Approve** → `5.1`
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
        return "5.1"


class ReflectionPhase(Phase):
    id = "5.1"
    name = "Reflection"
    short_description = "Reflector sub-agent emits proposals; auto-apply easy ones"

    def description_for_skill(self, simple_planning: bool = False) -> str:
        return """\
## Phase 5.1: Reflection

**Goal:** Reflect on the just-finished ticket and emit proposals — concrete improvements to rules, agent definitions, skills, memory, or workflow itself. Implement the easy ones directly; queue the rest for phase 5.2.

**Steps:**

1. Call `mcp__governed-workflow__workspace_get_reflection_context` — returns `{scope, branch_diff, review_findings, transcript}` for the ticket.
2. Spawn the `reflector` sub-agent via the `Agent` tool with `subagent_type="reflector"`. Hand it the context as the prompt verbatim — the agent will submit zero or more proposals via `mcp__governed-workflow__workspace_submit_proposal`.
3. Call `mcp__governed-workflow__workspace_list_proposals` to retrieve what the reflector submitted in this run.
4. For each proposal with `implementation_kind="auto"`, apply it now:
   - `memory_write` / `memory_delete` — you cannot edit files yourself (Edit/Write are disallowed at this phase). Spawn a `junior-backend-engineer` sub-agent to write/delete the markdown file under `~/.claude/projects/<encoded-project-path>/memory/` and update the `MEMORY.md` index if it exists. Encode the project path by replacing `/` and `.` with `-` (e.g. `/Users/me/Projects/foo` → `-Users-me-Projects-foo`); hand the sub-agent the proposal payload as the source of truth.
   - `rule_new` / `rule_update` — apply directly via the `mcp__governed-workflow__rule_create` / `mcp__governed-workflow__rule_update` MCP tools (no sub-agent needed).
   - On success, call `mcp__governed-workflow__workspace_resolve_proposal(proposal_id, status="executed", result_json=...)`; on tool failure, call with `status="failed"`; on conscious skip, call with `status="rejected"`.
5. Leave proposals with `implementation_kind="manual"` alone — phase 5.2 picks them up.
6. **Advance.** `workspace_advance` routes automatically: if any `manual` proposals remain in `status="proposed"`, you land in **5.2 Manual implementation**; otherwise you land in **6 Done**.

Auto proposals are applied here without a further human gate — phase 4.2 was the final user approval. The user can inspect the outcomes afterward via `mcp__governed-workflow__workspace_list_proposals` or directly in the DB."""

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        with get_db_ctx() as db:
            pending = count_pending_manual_proposals(db, ws["id"])
        return "5.2" if pending > 0 else "6"


class ManualImplementationPhase(Phase):
    id = "5.2"
    name = "Manual implementation"
    short_description = "Implement the manual proposals queued by 5.1"

    def description_for_skill(self, simple_planning: bool = False) -> str:
        return """\
## Phase 5.2: Manual implementation

**Goal:** Implement the manual proposals the reflector emitted in phase 5.1.

**Steps:**

1. Call `mcp__governed-workflow__workspace_list_proposals` with `implementation_kind="manual"` and `status="proposed"` — that's the queue.
2. For each proposal:
   - Read its `title`, `body`, and `payload_json` to understand what's being asked.
   - Spawn the appropriate sub-agent via the `Agent` tool:
     - `agent_new` / `agent_update` / `skill_new` / `skill_update` — spawn `middle-backend-engineer` (or `junior-backend-engineer` if trivial) with a prompt that describes the new/updated agent or skill, including the proposal's payload as the source of truth.
     - `workflow_improvement` — typically requires a multi-file change; spawn `senior-backend-engineer`.
   - On the sub-agent's success, call `mcp__governed-workflow__workspace_resolve_proposal(proposal_id, status="executed", result_json=<one-line summary>)`; on failure, call with `status="failed", result_json=<error summary>`; on conscious skip, call with `status="rejected"`.
3. **Advance to 6 Done** when the queue is drained.

Manual proposals must be implementable purely via `.claude/` workspace metadata (agents, skills, rules, memory) and the `rule_*` MCP tools — file edits outside `.claude/` are blocked at 5.2 by phase permissions, so any proposal that needs repo-code changes must become a new ticket instead."""

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return "6"


class DonePhase(Phase):
    id = "6"
    name = "Done"
    short_description = "Push and open the MR/PR; task complete"

    def description_for_skill(self, simple_planning: bool = False) -> str:
        return """\
## 6 Done

Push and MR/PR creation allowed. Task complete."""

    def validate(self, ws, body, project_path):
        locale = ws["locale"]
        return False, {"error": t("phase.done.complete", locale)}

    def next_phase(self, ws):
        return "6"


PHASES = [
    AgenticReviewPhase(),
    AddressFixPhase(),
    FinalApprovalPhase(),
    ReflectionPhase(),
    ManualImplementationPhase(),
    DonePhase(),
]
