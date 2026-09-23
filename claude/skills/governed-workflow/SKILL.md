---
name: governed-workflow
description: Orchestrates a governed multi-phase implementation workflow — assessment, research, planning, execution, review, and delivery — with backend-enforced phase gates, scope locking, and proof-driven research.
---

# Governed Workflow Skill

Multi-phase implementation workflow with backend-enforced transitions. Every phase advance is validated server-side — the orchestrator cannot self-certify readiness.

Phase detail lives in two companion skills: `/plan-preparation` (assessment through preparation review) and `/planning` (planning). Load the matching one on entering those phases.

---

## Agent Roles: All Agents Are Resumable Sub-agents

All agents — including plan-advisor — are resumable sub-agents. Spawn with `Agent(name: "...", subagent_type: "...", prompt: "...")` and continue via `SendMessage(to: "name", ...)`.

Agents execute their task and return. The orchestrator continues them for follow-up via `SendMessage(to: "<name>")`.

**Plan-advisor** is spawned once in Phase 0 with `run_in_background: true` and continued throughout the session via `SendMessage(to: "plan-advisor", ...)`. All other agents are spawned per-task and may be continued if needed.

### Spawn rules per role

| Role | When |
|------|------|
| **plan-advisor** | Spawned once at init (background), then messaged for assessment, impact analysis, planning, and each implementation sub-phase |
| senior-backend-engineer | Complex implementation sub-phases, including the fix cycles that follow them. Continue via SendMessage. Production code ONLY — never tests. |
| senior-backend-test-engineer | Complex test scenarios spanning write + fix cycles. Continue via SendMessage. Tests ONLY — always deployed AFTER engineer completes. |
| senior-code-validator | Continue via SendMessage when re-validation after fixes is expected |
| senior-code-researcher | Deep research spanning multiple rounds. Continue via SendMessage. |
| code-researcher | Research phase (parallel, one per topic). Variants: diff-researcher, web-researcher, ui-researcher depending on where the answer lives. |
| research-prover | Research proving phase |
| middle-backend-engineer | Implementation (stage 1), fixes, commit, and the post-review fix phase. Production code ONLY — never tests. |
| middle-backend-test-engineer | Implementation (stage 2, after engineer). Tests ONLY. |
| middle-code-validator | Validation sub-phase |
| review-validator | Post-review fix phase — after resolutions are set, verifies 'fixed' issues were actually fixed and 'false_positive' claims hold. |
| reflector | Reflection phase — spawned once with the reflection context embedded in its prompt. |

---

## Phase Map

Only the phases listed below are enabled for this project. The Edits, Commits, Push, and Gate columns reflect the runtime permission policy — anything OFF here is blocked server-side.

| Phase | Name | What happens | Edits | Commits | Push | Gate |
|-------|------|--------------|-------|---------|------|------|
| `0` | Init | Spawn plan-advisor | OFF | OFF | OFF | — |
| `1.0` | Assessment | plan-advisor surveys the codebase and raises research topics | OFF | OFF | OFF | — |
| `1.1` | Research | Parallel researcher sub-agents investigate each topic | OFF | OFF | OFF | — |
| `1.2` | Research Proving | Prover sub-agent verifies every research entry | OFF | OFF | OFF | — |
| `1.3` | Impact Analysis | Document cross-cutting effects before planning | OFF | OFF | OFF | — |
| `1.4` | Preparation Review | User reviews assessment, research, and impact analysis | OFF | OFF | OFF | USER |
| `2.0` | Planning | Orchestrator and plan-advisor draft the execution plan and scope | OFF | OFF | OFF | — |
| `3.x.0` | Implementation | Engineers implement sub-phase tasks (in-scope edits) | ON | OFF | OFF | — |
| `3.x.1` | Verification | Validators run; the backend routes onward from the result | OFF | OFF | OFF | — |
| `3.x.2` | Fix Review | Engineers address validation or review failures | ON | OFF | OFF | — |
| `3.x.3` | Commit Approval | User reviews the diff and approves the commit message | OFF | OFF | OFF | USER |
| `3.x.4` | Commit | Engineer commits the staged changes | OFF | ON | OFF | — |
| `4.0` | Agentic Review | Headless review pipeline runs file and integration reviewers | OFF | OFF | OFF | — |
| `4.1` | Address Fix | Engineers address review findings across the merged scope | ON | ON | OFF | — |
| `4.2` | Final Approval | User reviews the resolved findings and approves delivery | OFF | OFF | OFF | USER |
| `5.1` | Reflection | Reflector sub-agent emits proposals; auto-apply easy ones | OFF | OFF | OFF | — |
| `5.2` | Manual implementation | Implement the manual proposals queued by the reflector | OFF | OFF | OFF | — |
| `6` | Done | Push and open the MR/PR; task complete | OFF | OFF | ON | — |

Phases are stored as strings. Execution items `3.N.K` expand at plan-validation time; the row labelled `3.x.K` describes every concrete `N` in that family.

---

## Session Start / Recovery

**Every session — fresh or resumed — starts here:**

1. Call `workspace_get_state`
2. Read `phase` and `previous_sessions_count`

**Fresh start** (`phase == "0"` and `previous_sessions_count == 0`): proceed to Phase 0.

**Recovery** (`phase > "0"` or `previous_sessions_count > 0`): the previous session ended (compaction, restart, or manual resume). **The plan-advisor from the previous session is gone — you MUST re-spawn it.**

1. Call `workspace_get_progress` to reconstruct what happened
2. **IMMEDIATELY re-spawn plan-advisor as a background sub-agent** (any phase past init):
   ```
   Agent(
     name: "plan-advisor",
     subagent_type: "plan-advisor",
     run_in_background: true,
     prompt: "You are the plan-advisor in this governed workflow session.
              Workspace: {working_dir}
              Wait for instructions from the orchestrator."
   )
   ```
3. Continue from the current phase — message the plan-advisor via `SendMessage(to: "plan-advisor", ...)`

---

## Agent Selection Matrix

When assigning tasks to agents, use this decision matrix:

| Task type | Agent | Never assign to |
|-----------|-------|-----------------|
| Production code (CRUD, services, configs) | `middle-backend-engineer` | test engineers |
| Complex production code (vague specs, unknown root cause) | `senior-backend-engineer` | test engineers |
| Tests for new/changed code | `middle-backend-test-engineer` | backend engineers |
| Complex test scenarios (edge cases, integration) | `senior-backend-test-engineer` | backend engineers |
| Code quality review | `middle-code-validator` or `senior-code-validator` | — |

**Critical rule: Tests MUST be written by a separate test engineer agent, NEVER by the same agent that implemented the production code.** The implementing agent is not objective — they will test what they think the code does, not what it should do. Test engineers review the implementation with fresh eyes and write tests that validate behavior independently.

**Execution order within a sub-phase:**
1. Deploy backend engineer(s) for production code
2. Deploy test engineer(s) for tests — AFTER the production code is written
3. Both share the same sub-phase scope; test engineer reads the implementation to understand what to test

When planning tasks, structure each sub-phase with separate tasks for implementation and testing, assigned to the appropriate agent types. Never create a single task that asks an engineer to "implement + write tests".

---

## 0 Init — Spawn Plan-Advisor

**Actors**: Orchestrator

The workspace already exists (created via admin panel). This phase spawns the plan-advisor as a background sub-agent.

### Steps

1. Spawn `plan-advisor` as a background sub-agent:

```
Agent(
  name: "plan-advisor",
  subagent_type: "plan-advisor",
  run_in_background: true,
  prompt: "You are the plan-advisor in this governed workflow session.
           Your role definition is the plan-advisor agent.
           Workspace: {working_dir}
           Your role: assess the codebase, advise on planning, review the execution plan.
           Wait for instructions from the orchestrator."
)
```

2. Call `workspace_advance` to move to phase 1.0.

**The plan-advisor is always reachable via `SendMessage(to: "plan-advisor", ...)`.**

---

## 1.0 Assessment

**Actor**: plan-advisor (messaged — NOT a new sub-agent)

If the plan-advisor is not yet spawned (skipped Phase 0 or session recovery), spawn it first (see Phase 0 steps).

Message the plan-advisor with the structured assessment brief from `/plan-preparation`.

When assessment is complete:
1. Call `workspace_update_progress` for phase `"1.0"` with a non-empty summary
2. Call `workspace_advance`

**Advancing from 1.0** requires: progress entry `"1.0"` with a non-empty summary AND at least one open research discussion (`type='research'`).

---

## 1.1 Research

**Actors**: Researcher sub-agents (parallel, one-shot)

Deploy parallel researcher sub-agents — one per investigation topic identified in assessment (researcher choice: see `/plan-preparation`). Each calls `workspace_save_research` with findings and typed proofs; the proof formats are defined in the researcher agents.

Every unresolved research discussion (raised during assessment) MUST be linked to at least one research entry before advancing.

Call `workspace_advance(no_further_research_needed=true)` when all researchers complete.

**Advancing from 1.1** requires: `no_further_research_needed=true`, every open research discussion has linked research, at least 1 research entry, all entries valid.

---

## 1.2 Research Proving

**Actor**: Prover sub-agent (Opus, one-shot)

Deploy one prover sub-agent:

```
Agent(
  subagent_type: "research-prover",
  prompt: "Verify all research entries for this workspace. Mark each as proven or rejected.
           Workspace: {working_dir}"
)
```

The prover ONLY verifies — it does NOT research. It calls `workspace_prove_research` for each entry DIRECTLY — the orchestrator does NOT need to call it. Its return is the completion notice — ask it for a short proven/rejected list rather than re-reading every entry.

If any research is rejected: re-deploy the original researcher sub-agents for those topics (to fix their proofs), then re-deploy the prover.

When all research is proven (prover confirms):
1. Call `workspace_update_progress` for phase `"1"`
2. Call `workspace_advance`

**Advancing from 1.2** requires: all research entries proven (none rejected, none unproven) + progress entry `"1"`.

---

## 1.3 Impact Analysis

**Actors**: Orchestrator + plan-advisor

Before planning, document the cross-cutting effects of this change, following `/plan-preparation` (advisor brief, six-field structure, research loop).

Save the result via `workspace_set_impact_analysis` with the six fields. The Pre-planning tab renders it alongside the research summaries so the user can review everything before the preparation gate.

When complete:
1. Call `workspace_update_progress` for phase `"1.3"`
2. Call `workspace_advance`

**Advancing from 1.3** requires: progress entry `"1.3"`. (Impact analysis should be populated — the user will reject at the preparation review gate if it isn't.)

---

## 1.4 Preparation Review (USER GATE)

The user reviews the full preparation package in the Pre-planning tab: assessment summary, research findings, and impact analysis.

- **Approve** → the backend advances you to the next enabled phase
- **Reject** → the backend moves you back into the preparation phases with comments

**Waiting**: do not poll — see User Gates — Waiting below.

**After rejection**: follow User Gate Rejection below. Here the work is: deploy more researcher sub-agents (and update impact analysis later) to address the feedback, and re-run every preparation phase you were returned to before advancing back to the gate.

---

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

**Advancing from 2.0** requires: valid plan with ≥1 execution sub-phase (each with a non-empty `scope.must`), plan_status='approved', ≥1 acceptance criterion, no proposed criteria, and progress entry `"2"`.

---

## 3.N.0 Implementation

**Actors**: Engineer sub-agents, then test engineer sub-agents | **Code edits: ON (in sub-phase scope)**

Deploy in two stages:

**Stage 1 — Production code**: Deploy engineer sub-agent(s) for the implementation tasks.

**Stage 2 — Tests**: After engineers complete, deploy test engineer sub-agent(s) to write tests for the new/changed code. Test engineers read the implementation but write tests independently — they are NOT briefed on "how the code works", only on "what it should do" (from the task description and scope).

If during implementation an issue arises that requires changing the approach or scope, message the plan-advisor to discuss:

```
SendMessage(
  to: "plan-advisor",
  content: "Implementation issue in sub-phase {N}: {describe the problem}.
            The original plan assumed {X} but we found {Y}. What's the best path forward?"
)
```

If the user requests additional work or new requirements emerge, use `workspace_extend_plan` to add a new sub-phase rather than rewriting the entire plan. This preserves existing sub-phases and their progress.

Call `workspace_advance` when both implementation and tests are complete.

**Advancing from 3.N.0** requires: at least 1 file changed per `must`-scope entry.

---

## 3.N.1 Validation

**Actors**: Validator sub-agents | **Code edits: OFF**

Deploy validator sub-agents (`middle-code-validator` / `senior-code-validator`) for compilation check + code quality review. Each validator returns its PASS/FAIL findings directly to you as its response — there is no tool to submit them. Verification profiles assigned to the workspace (configured via `workspace_assign_verification_profile`) run automatically server-side **at the advance gate**.

Call `workspace_advance`. The verification run executes during the advance and the phase machine routes off its result:
- Verification failed → the advance lands you in the fix sub-phase — it does NOT block. Fix the failures there, then advance back here to re-validate.
- Verification passed, or no profiles are assigned → the backend routes you onward to the next enabled sub-phase

---

## 3.N.2 Fixes

**Actors**: Engineer sub-agents | **Code edits: ON (in sub-phase scope)**

You arrive here from a failed verification run (or a code-review rejection). Call `workspace_get_verification_results` to see exactly which steps failed, and `workspace_get_comments` for any user feedback. Deploy engineer sub-agents to fix the issues — edits are allowed here. Call `workspace_advance` when done to re-validate; the backend loops you back through verification until it passes.

---

## 3.N.3 Code Review (USER GATE)

User reviews the diff in the admin panel.

- **Approve** (+ optional commit message) → the backend advances you to the next enabled sub-phase
- **Reject** → the backend moves you back into the fix sub-phase with comments

**Waiting**: do not poll — see User Gates — Waiting below.

**After rejection**: you land in a phase with code edits ON. Follow User Gate Rejection below — deploy engineer sub-agents to address the feedback, then advance.

---

## 3.N.4 Commit

**Actor**: Engineer sub-agent | **Commits: ON**

Commit all changes. Use the commit message from `workspace_get_state` (`context.commit_message`) or generate one per git-rules.md.

Call `workspace_advance(commit_hash="{hash}")`.

**Advancing from 3.N.4** requires: valid commit hash + progress entry `"3.N"`. The backend routes you to the next execution sub-phase, or onward past execution when this was the last one.

---

## 4.0 Blind Code Review (automated)

**Actors**: Headless review pipeline (background daemon) | **Code edits: OFF**

On entry to 4.0 the admin panel **automatically launches** the headless review pipeline, running the stages selected by the workspace's review mode:

- **Per-file fan-out** — one reviewer per changed file, local issues only
- **Integration pair** (blind, run concurrently) — **architecture-reviewer** (SRP/OCP, coupling, layer boundaries, clean-code principles, naming, method/class size, DRY) and **correctness-reviewer** (business-logic correctness, edge cases, error handling, security)
- **Resolution adjudicator** (only in the most thorough review mode) — runs after the integration pair and dismisses invalid findings as false_positive/out_of_scope, leaving genuinely valid findings open for you to address

Some or all of these stages may be skipped depending on the workspace's review mode — check the pipeline status to see which stages actually ran.

**Do NOT manually dispatch reviewers.** The pipeline is already running (unless the workspace's review mode is `manual`, in which case no pipeline starts and this phase relies on your own review plus the user's approval). Manual dispatch would duplicate work and confuse findings.

### What you do at 4.0

1. The pipeline runs in the background. Call `workspace_review_pipeline_summary` once; if `is_complete` is not yet true, tell the user the review is running and end the turn — do not poll. Check it again once when the user messages or a scheduled check fires.
2. When `is_complete=true`:
   - Call `workspace_get_review_issues` to see the findings.
   - Call `workspace_update_progress(phase="4.0", summary="Pipeline complete. N findings.")`.
   - Check `is_ok=true`. If `files_failed > 0` or `integration_failed > 0`, decide: ask the user to re-trigger via the Run Review button on the workspace page, OR proceed with the partial result if the failures are recoverable. Never call the admin HTTP API directly.
   - Call `workspace_advance` to move to 4.1.

If the pipeline failed mid-run, the reason is exposed only via `workspace_review_pipeline_summary` (`failed_files_errors`, `integration_errors`, top-level `error`) — never as a discussion. Inspect those fields and decide whether to re-trigger or proceed.

**Advancing from 4.0** requires: progress entry for phase `"4.0"`.

---

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

**Advancing from 4.1** requires: progress entry `"4"` + all review items resolved by user.

---

## 4.2 Final Approval (USER GATE)

- **Approve** → the backend advances you to the next enabled phase
- **Reject** → the backend moves you back into the fix phase

**Waiting**: do not poll — see User Gates — Waiting below.

**After rejection**: follow User Gate Rejection below — address the feedback (fix code, update resolutions), then advance.

---

## Phase 5.1: Reflection

**Goal:** Reflect on the just-finished ticket and emit proposals — concrete improvements to rules, agent definitions, skills, memory, or workflow itself. Implement the easy ones directly; queue the rest for phase 5.2.

**Steps:**

1. Call `mcp__governed-workflow__workspace_get_reflection_context` — returns `{scope, branch_diff, review_findings, transcript}` for the ticket.
2. Spawn the `reflector` sub-agent via the `Agent` tool with `subagent_type="reflector"`. Hand it the context as the prompt verbatim — the agent will submit zero or more proposals via `mcp__governed-workflow__workspace_submit_proposal`.
3. The reflector's report lists each submitted proposal as `id — implementation_kind — type — title`. If it lists no `auto` proposals, skip to step 5. Otherwise call `mcp__governed-workflow__workspace_list_proposals(implementation_kind="auto", status="proposed")` once to get their payloads.
4. For each proposal with `implementation_kind="auto"`, apply it now:
   - `memory_write` / `memory_delete` — you cannot edit files yourself (Edit/Write are disallowed at this phase). Spawn a `junior-backend-engineer` sub-agent to write/delete the markdown file under `~/.claude/projects/<encoded-project-path>/memory/` and update the `MEMORY.md` index if it exists. Encode the project path by replacing `/` and `.` with `-` (e.g. `/Users/me/Projects/foo` → `-Users-me-Projects-foo`); hand the sub-agent the proposal payload as the source of truth.
   - `rule_new` / `rule_update` — apply directly via the `mcp__governed-workflow__rule_create` / `mcp__governed-workflow__rule_update` MCP tools (no sub-agent needed).
   - On success, call `mcp__governed-workflow__workspace_resolve_proposal(proposal_id, status="executed", result_json=...)`; on tool failure, call with `status="failed"`; on conscious skip, call with `status="rejected"`.
5. Leave proposals with `implementation_kind="manual"` alone — the manual implementation phase picks them up.
6. **Advance.** `workspace_advance` routes automatically: if any `manual` proposals remain in `status="proposed"` you land in manual implementation, otherwise the backend takes you onward to delivery.

Auto proposals are applied here without a further human gate — the final approval gate has already passed. The user can inspect the outcomes afterward via `mcp__governed-workflow__workspace_list_proposals` or directly in the DB.

---

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
3. **Advance** when the queue is drained.

Manual proposals must be implementable purely via `.claude/` workspace metadata (agents, skills, rules, memory) and the `rule_*` MCP tools — file edits outside `.claude/` are blocked at 5.2 by phase permissions, so any proposal that needs repo-code changes must become a new ticket instead.

---

## 6 Done

Push and MR/PR creation allowed. Task complete. Right after the MR/PR is created, call `workspace_save_pr` with the resulting URL (and the repo name in multi-repo workspaces) so the admin panel can link to it.

---

## MCP Tools

The orchestrator only needs to understand the workflow-shaping tools below. The rest are granted via this agent's frontmatter and self-describe through their own `description` strings and parameter annotations — consult them inline when you reach for one.

### Core tools you must understand

| Tool | Why it needs explanation |
|------|--------------------------|
| `workspace_get_state` | Single source of truth for `phase`, `scope`, `plan`, `context`, `previous_sessions_count`, `progress_summary`. Call once at session start and once when a user gate may have changed state. After `workspace_advance`, use the `phase` it returns instead of re-fetching. |
| `workspace_advance` | Drives the phase machine. The backend picks the next phase from server-side rules. Required arguments vary by phase — consult the per-phase blocks below for what to pass at each advance. |
| `workspace_set_plan` | Writes or replaces the execution plan. Each execution item carries a `scope` field (must/may) — there is no separate scope call. Planning-phase only; switches `plan_status` back to `pending`. |
| `workspace_extend_plan` | Appends a sub-phase to an already-approved plan. Each new item carries its own `scope`. Use instead of `workspace_set_plan` when execution surfaces new work — avoids invalidating prior sub-phases. |
| `workspace_update_subphase` / `workspace_delete_subphase` / `workspace_set_plan_diagrams` / `workspace_set_plan_description` | Granular plan edits — see `/planning` for which ones reset plan approval. |
| `workspace_propose_criteria` | Records acceptance criteria the user reviews at the plan approval gate. Valid in the planning phase only; required before advancing past it. |
| `workspace_delete_criteria` | Deletes a proposed acceptance criterion. Allowed only while it is not yet accepted — plan approval accepts all proposed criteria, after which deletion is refused. |
| `workspace_post_discussion` | Raises an architectural or research question the user resolves in the admin panel. Required by some advance guards (e.g. an open research discussion before leaving assessment). |
| `workspace_resolve_review_issue` | Resolve one or more review issues in a single call (pass an array of ids). Agents set resolution (`fixed` / `false_positive` / `out_of_scope`) on findings. The user still has to mark each one resolved in the panel — this only records what was done. |
| `workspace_get_reflection_context` | Returns the scope, branch diff, review findings, and filtered transcript fed to the reflector. Call once on entry to the reflection phase. |
| `workspace_list_proposals` | Reads what the reflector emitted. Filter by `implementation_kind` (`auto` to apply now, `manual` to queue for the manual implementation phase). |
| `workspace_resolve_proposal` | Marks a proposal `executed`, `failed`, or `rejected` after acting on it. Pass `result_json` with the outcome summary. |
| `workspace_attach_repo` | Multi-repo workspaces only. The workspace dir contains only the repo worktrees already attached — before editing a repo that isn't present yet, call this with the repo name to create its worktree and attach it. Never edit files outside the workspace dir. |
| `workspace_save_pr` | Call immediately after creating a merge/pull request, passing the resulting URL (and the repo name in multi-repo workspaces) so the admin panel can link to it. |

Full tool roster is granted via this agent's frontmatter; consult tool descriptions inline.

---

## User Gates — Waiting

When `workspace_advance` returns 202 (awaiting approval), tell the user the gate is waiting and end the turn — do not poll. Re-check `workspace_get_state` once when the user messages or a scheduled check fires.

## User Gate Rejection — Critical Rule

**When a user gate rejects, the backend moves you to the fix/rework phase. You MUST fix before advancing.**

The destination is chosen server-side from the enabled phase set — this document does not name it, because it depends on which phases this project has turned on.

**NEVER call `workspace_advance` immediately after detecting a rejection.** Always: (1) read the phase you are now in from the `workspace_get_state` result that showed the rejection, (2) read `workspace_get_comments` for feedback, (3) do the work, (4) then advance.

---

## Review Item Resolution Flow

Review items (scope='review' discussions) follow a two-step lifecycle:

1. **Agent sets resolution**: After addressing findings, call `workspace_resolve_review_issue([ids], "fixed"|"false_positive"|"out_of_scope")` with an array of issue ids. This marks what the agent did but does NOT resolve the items.
2. **User resolves**: At a user gate — code review or final approval — the user reviews resolutions and resolves each item in the admin panel.

The `ReviewGuard` only blocks at user gate phases — it does NOT block during implementation or fixes. The agent moves through the fix and re-validation sub-phases with unresolved review items still open; the user resolves them at a gate.

---

## Advance Error Handling

| Code | Meaning |
|------|---------|
| 200 | Advanced |
| 202 | User gate — tell the user and end the turn (see User Gates — Waiting) |
| 422 | Validation failed — read error, fix, retry |
| 409 | Already at gate or phase changed |

On 422: read the error message. It names exactly what is missing. Fix it, then call `workspace_advance` again.

---

## Progress Documentation

Some phases require a progress entry before they will let you advance. Use `workspace_update_progress`.

Each phase section above states its own requirement — this document deliberately does not tabulate transitions, because which phase follows which is decided server-side from the enabled phase set.

Progress is used for phase gate validation, session recovery after compaction, and retrospective review.

## Human-Facing Reports

When the orchestrator owes the human user a report or explanation (findings, a summary, decision rationale) that should persist beyond the chat transcript, put it in a plain markdown file, not a chat-only reply; see the `scratchpad` skill for where and how.
