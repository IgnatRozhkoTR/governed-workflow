---
name: planning
description: Guides the orchestrator through Phase 2.0 (Planning) of the governed workflow — structuring the execution plan (with per-item scope), proposing acceptance criteria, and collaborating with the plan-advisor teammate.
---

# Planning Skill

Phase 2.0 of the governed workflow. The orchestrator and plan-advisor teammate collaborate to produce an execution plan with scope embedded in each execution item, and acceptance criteria. The plan must pass backend validation and user review before execution begins.

---

## Plan Structure

The execution plan has two audiences: **the user** (who reviews it in the admin panel) and **the agents** (who execute it). Structure accordingly.

### Plan description

The `description` field is a paragraph answering four questions:

1. **What** are we building?
2. **Why** — motivation from the ticket
3. **How** — high-level approach (not implementation details, but the architectural direction)
4. **What is out of scope** — explicitly state boundaries

This paragraph is the first thing the user reads. Keep it under 5 sentences. No class names, no file paths.

### Sub-phases

Each sub-phase has `id`, `name`, `tasks`, and `scope`. Sub-phases map to execution cycles (3.1, 3.2, ...) — each goes through implementation, validation, review, and commit.

**Default: one sub-phase.** A small or single-area change — for example, adding a service and repository layer to an existing backend feature — is always exactly ONE sub-phase. Do not split it.

**Split only for genuinely large jobs** that change a lot of code across clearly different areas, where each area should be fully implemented and validated before the next area begins. A concrete example of a large new feature that warrants three sub-phases:

1. Sub-phase 1 — backend: implement all changes across all layers (entity, repository, service, controller) including unit tests, fully. Validated and committed before frontend work begins.
2. Sub-phase 2 — frontend: after the backend is implemented and validated, implement the whole frontend plus its UI/unit tests with full coverage. Validated and committed before E2E work begins.
3. Sub-phase 3 — end-to-end: large no-mock UI/Cucumber/E2E tests that span the full stack.

**Do NOT split when:**
- Two changes depend on each other (e.g., an entity and the service that uses it) — these belong in the same sub-phase even if they're in different files.
- The split would create sub-phases so small they don't warrant independent review.
- You're splitting just to organize by file or class — that's what tasks within a sub-phase are for.
- The whole job is backend-only, even if it touches several layers — a backend-only feature, no matter how many files, is one sub-phase.

**The litmus test: will the reviewer get lost?** If the combined diff would be large and span multiple concerns (backend AND frontend AND E2E), split it. If the reviewer can follow the changes as a single coherent unit, keep it together. When in doubt, one sub-phase is always the right answer for anything backend-only or small.

### Tasks — two-layer structure

Every task has a human layer and an agent layer:

- **`title`**: Human-readable summary. One sentence describing WHAT this step does at a business level. No class names, no method names, no parameter values. The user reads this to understand the plan at a glance.
  - Good: "Create the service that generates default narrative segments from a chapter template"
  - Bad: "Create NarrativeService with getTemplate(), saveTemplate(), generateDefault()"

- **`description`**: Technical specification for the implementing agent. Class names, method signatures, parameter values, file paths, API contracts, edge cases to handle. This is the agent's work order — it must contain everything the agent needs to do the work without guessing.
  - Example: "NarrativeService with methods getTemplate(UUID chapterId), saveTemplate(NarrativeTemplate), generateDefault(UUID chapterId), regenerateSegment(UUID segmentId). Hardcoded taxonomy version = 2023-12-22. Use JmixDataRepository for persistence. Return Optional where absence is possible."

- **`files`**: Array of file paths the task will touch. Used for scope enforcement and parallel conflict detection.

- **`agent`**: Agent type to assign. See the agent selection matrix in the main SKILL.md.

- **`group`**: Optional. Tasks with the same group name run in parallel (fork/join). Tasks without a group or with unique group names run sequentially. Groups execute in order of first appearance within the sub-phase.

- **`status`**: Always `"pending"` at plan creation.

**Separation rule**: Never combine "implement + write tests" into a single task. Production code and test code are always separate tasks assigned to different agent types.

### System diagrams

Required for every plan. The `systemDiagram` field is an array of Mermaid diagrams:

1. **Class/entity diagram** (required): Key classes, entities, or components and their relationships. Use Mermaid `classDiagram` syntax.
2. **Sequence diagram(s)** (required): Control flow through the system for the main use cases. Use Mermaid `sequenceDiagram` syntax. Create one diagram per distinct flow — multiple sequence diagrams are encouraged when the feature involves multiple user-facing flows.

Format:
```json
"systemDiagram": [
  {"title": "Class Diagram", "diagram": "classDiagram\n  class UserService {\n    +createUser()\n  }"},
  {"title": "Auth Flow", "diagram": "sequenceDiagram\n  Client->>+API: POST /login\n  API->>+UserService: authenticate()"}
]
```

---

## Scope Definition

Scope is defined **per execution item**, embedded directly inside each item submitted via `workspace_set_plan` or `workspace_extend_plan`. There is no separate `workspace_set_scope` call — scope lives in the plan.

Each execution item carries a `scope` field with `must` and `may` arrays:

- **must**: Broad areas where absence of changes means the task is incomplete. Keep this list short — if the ticket says "add BDD scenarios", the BDD module is must-scope.

- **may**: Specific files and packages identified during planning. Most paths from the execution plan belong here. Permitted but not required.

Format inside each execution item:
```json
{
  "id": "3.1",
  "name": "Backend implementation",
  "scope": {
    "must": ["src/main/java/**/entity/", "src/main/java/**/service/"],
    "may": ["src/main/resources/db/changelog/", "src/main/java/**/util/"]
  },
  "tasks": [...]
}
```

During execution, the hook enforces the current sub-phase's scope automatically. When the user approves the plan in the admin panel (while the workspace is at 2.0), scope is approved as part of the plan — there is no separate scope approval step.

For test-type acceptance criteria, add the test file paths to the relevant sub-phase's `must` array.

---

## Acceptance Criteria

Acceptance criteria are **authored here, during planning (phase 2.0)**. This is the canonical place to propose criteria via `workspace_propose_criteria`. Calling `workspace_propose_criteria` before phase 2.0 is rejected by the backend.

Criteria are validated programmatically when the last sub-phase commits. If any accepted criterion with a validator fails, advancement to review is blocked. Approving the plan also accepts all proposed criteria — there is no separate per-criterion accept/reject step.

### Reviewing existing criteria

Call `workspace_get_criteria()` for the full criteria list. The user may have defined criteria during workspace setup. Review them for completeness — do they cover the ticket's requirements?

### Proposing additional criteria

Call `workspace_propose_criteria` for any gaps. Supported types:

**For `unit_test` or `integration_test`:**

Create **one criterion per test class** — group all test methods for the same file into a single call. Do NOT create a separate criterion for each test method.

```
workspace_propose_criteria(
  type="unit_test",
  description="UserService creation and validation logic",
  details_json='{"file": "src/test/java/com/example/UserServiceTest.java", "test_names": ["createUser_shouldReturnUser_whenValid", "createUser_shouldThrow_whenEmailTaken"]}'
)
```

**Mandatory rules for `unit_test` and `integration_test` criteria:**

1. **`details_json` MUST contain both `file` and `test_names`** — these are the fields the validator checks. Putting file paths or test names in the `description` field does nothing; the validator ignores `description` for automated checks.

2. **`file`** — full path to the test class, relative to project root. Use the project's actual directory structure (check existing tests with Glob/Grep to confirm the path convention).

3. **`test_names`** — array of exact test method names. **Before proposing any test-type criterion, you MUST read actual existing test files of the same kind (unit / integration / BDD) in the repository and understand their naming structure.** This is not optional. Criteria are verified by a literal substring check — the validator searches for the exact method name as a string in the test file at commit time. If the name does not match precisely, validation fails and the commit is blocked. The test names **cannot be changed** after the plan is approved.

   How to get the names right:
   - Use Glob to find test files in the same module/package (`**/UserServiceTest.java`, `**/*IntegrationTest.java`, etc.)
   - Read those files to see the exact naming pattern in use
   - Common patterns: `methodName_shouldBehavior_whenCondition`, `test_method_name_condition`, `testMethodNameCondition` — but only the pattern actually used in this repo is correct
   - **Match the convention exactly, character for character** — the test names you propose will be searched as literal substrings at validation time

4. **One call per test class** — if you need unit tests for `UserService` and `OrderService`, that's two `workspace_propose_criteria` calls (one for `UserServiceTest`, one for `OrderServiceTest`), not one call per test method and not one call with mixed files.

5. **`description`** is a human-readable summary shown in the admin panel. Keep it short — the technical details belong in `details_json`.

**For `bdd_scenario`:**
```
workspace_propose_criteria(
  type="bdd_scenario",
  description="User registration end-to-end flow",
  details_json='{"file": "features/user-registration.feature", "scenario_names": ["User registers with valid data", "User sees error for duplicate email"]}'
)
```

**For `custom`:**
```
workspace_propose_criteria(
  type="custom",
  description="Liquibase changelog applies cleanly",
  details_json='{"instruction": "Run liquibase update and verify no errors on a clean database"}'
)
```

**IMPORTANT**: The `details_json` parameter must be a JSON-encoded STRING, not a dict object. Always use `json.dumps()` or construct the string manually.

### Gate rule

All acceptance criteria must be accepted (or deleted) before the plan can advance to user review. Criteria with status `proposed` or `rejected` will block advancement.

---

## Collaboration with Plan-Advisor

The plan-advisor is a persistent teammate, not a sub-agent. It was spawned in Phase 0 and must be resumed, never re-spawned.

### Step 1 — Resume and present

Resume the plan-advisor with a high-level plan outline:

```
Agent(
  resume: {plan_advisor_id},
  prompt: "We are in the planning phase. Review the research findings via workspace_get_state.
           Here is my proposed plan outline:
           {outline — sub-phases, task summaries, scope boundaries}
           Review every task: agent selection, file scope, task clarity, dependencies, gaps.
           Send your review as a numbered list with verdict per task (OK or CONCERN)."
)
```

### Step 2 — Review and discuss

The plan-advisor reviews every task and sends a numbered list with verdicts. For each concern:
- Accept and adjust the plan, OR
- Reject with reasoning

Discuss until consensus on each point.

### Step 3 — Expansion

After consensus, the plan-advisor expands the plan with technical details (class names, method signatures, file paths in task descriptions).

### Step 4 — Orchestrator review

Review the expansion. Send numbered remarks on specific tasks if needed. The plan-advisor responds and adjusts. **One round maximum**, then finalize.

### Step 5 — Finalize

Execute in order:
1. `workspace_set_plan` — full plan JSON with execution items, each carrying its own `scope` (must/may). Resets plan approval status to pending.
2. `workspace_update_progress` for phase `"2"` with a summary of the plan.
3. `workspace_advance` — this enters the user review wait at 2.0. The workspace stays at 2.0 while the user reviews and approves the plan in the admin panel. Approving the plan also approves scope and cascades all proposed acceptance criteria to accepted. Once approved, the backend advances directly to 3.1.0.

**Advance 2.0 -> 3.1.0** requires: valid plan with at least 1 execution sub-phase + progress entry `"2"` + >=1 acceptance criterion with no pending/rejected criteria + plan approved by user in the admin panel. There is no separate 2.1 gate phase and no separate scope approval — one plan approval covers everything.

---

## Anti-patterns

| Do NOT | Instead |
|--------|---------|
| Stuff technical details into task titles | Titles are for humans — keep them business-level |
| Create a sub-phase per file | Sub-phases are for logical chunks — layers, modules, concerns |
| Inflate the plan with unnecessary sub-phases | Fewer sub-phases is better; one is fine for simple tasks |
| Skip acceptance criteria | They are validated programmatically — missing criteria means gaps slip through |
| Combine "implement + write tests" in one task | Always separate — different agents, different perspectives |
| Use `proposed` or `rejected` criteria status at advance time | All criteria must be `accepted` or deleted before advancing |
| Brief the plan-advisor with implementation assumptions | Present the outline, let the advisor form independent judgment |
| Pass `details_json` as a dict object | It must be a JSON-encoded string |
| Put file paths or test names in `description` instead of `details_json` | `description` is for humans; `details_json.file` and `details_json.test_names` are what the validator reads |
| Create one criterion per test method | Group all methods for the same test class into one criterion with the `test_names` array |
| Invent test names without reading existing tests first | Read actual test files of the same kind before proposing; names are a literal substring check and cannot be changed after plan approval |
