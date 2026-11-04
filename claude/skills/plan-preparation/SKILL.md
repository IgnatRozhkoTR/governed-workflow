---
name: plan-preparation
description: Guides the orchestrator through phases 1.0-1.4 of the governed workflow — assessment, research, research proving, impact analysis, and preparation review. Produces a thorough, structured foundation before planning begins.
---

# Plan Preparation Skill

Phases 1.0 through 1.4: take a ticket from raw requirements to a fully researched, impact-analyzed, user-approved foundation ready for planning. Every phase builds on the previous one. No shortcuts — gaps discovered here prevent rework during execution.

---

## Phase 1.0: Assessment

**Actor**: plan-advisor (messaged via `SendMessage(to: "plan-advisor")`, NOT a new sub-agent)

If the plan-advisor is not running (skipped Phase 0 or session recovery), spawn it first (see Phase 0 in the governed-workflow skill).

### Goal

Produce a structured assessment that maps the ticket to the codebase and surfaces everything that needs investigation before planning.

### Prompt

Resume the plan-advisor teammate with an explicit structure requirement:

```
SendMessage(
  to: "plan-advisor",
  content: "Begin assessment. Read workspace_get_state for context (ticket, working_dir, context notes).

           Produce a STRUCTURED assessment with these sections:

           1. TICKET RESTATEMENT — rephrase the ticket in your own words. This catches
              misunderstandings early. If your restatement doesn't match the ticket intent,
              the orchestrator will correct you before research begins.

           2. AFFECTED AREAS — not file paths, but concepts: which APIs, which user flows,
              which data pipelines, which business domains are touched. Think in terms of
              what the system does, not where the code lives.

           3. API IMPACT — which endpoints are created, modified, or removed. What changes
              in request/response contracts. If no API changes, say so explicitly.

           4. DATA FLOW — where do key values come from? Config file? User input? External
              API? Database lookup? Computed at runtime? Trace the origin of every important
              parameter the ticket mentions.

           5. TICKET GAPS — what the ticket doesn't specify. What decisions it leaves to us.
              Be specific: 'ticket says add validation but doesn't specify which fields' is
              useful. 'Ticket could be clearer' is not.

           6. DEPENDENCIES — what other modules, services, or teams consume what we're
              changing. If we modify an API response, who reads it? If we change a DB
              schema, what else queries that table?

           7. RESEARCH QUESTIONS — what needs deeper investigation before we can plan.
              Each question becomes a research topic in phase 1.1. Be specific enough
              that a researcher knows exactly what to look for.

           Raise any discussion points via workspace_post_discussion (type: 'research' for
           questions needing investigation, 'general' for architectural decisions).

           Report your findings in this exact structure."
)
```

### After assessment completes

1. Review the assessment. If the ticket restatement is wrong or incomplete, correct the plan-advisor and have them revise before proceeding.
2. Call `workspace_update_progress` for phase `"1.0"` with a summary covering: ticket restatement, affected areas count, research questions count, and any discussion points raised.
3. Call `workspace_advance`.

**Advance 1.0 -> 1.1** requires: progress entry `"1.0"` with non-empty summary AND at least one open research discussion (type='research').

---

## Phase 1.1: Research

**Actors**: Researcher sub-agents (parallel, one-shot)

### Goal

Answer every research question from the assessment. Each researcher investigates one topic and saves structured findings with verifiable proofs.

### Deploying researchers

One sub-agent per research question from the assessment. Choose the researcher type based on where the answer lives:

| Answer lives in... | Researcher type | Proof type |
|---------------------|-----------------|------------|
| Codebase (classes, configs, patterns) | `code-researcher` or `senior-code-researcher` | `"code"` |
| External docs, libraries, frameworks | `web-researcher` | `"web"` |
| Git history (when/why something changed) | `diff-researcher` | `"diff"` |

Use `senior-code-researcher` when the topic is complex (deep call chains, framework internals, cross-module interactions). Use `code-researcher` for straightforward lookups (finding classes, checking configs, listing usages).

### Summary requirement

Every researcher MUST pass a 2-3 sentence `summary` to `workspace_save_research`: what was found, what it means for the ticket, any surprises. Specific facts, not "investigated X, found several things".

### Discussion linking

If a research question originated from a discussion (posted via `workspace_post_discussion` in phase 1.0), pass the `discussion_id` to `workspace_save_research`. This links the research findings to the discussion that raised the question, and is required for advancing past the research phase — all unresolved research discussions must have linked findings.

Proof formats (`code` / `web` / `diff`) are defined in the researcher agents — do not repeat them in briefs.

### When all researchers complete

Call `workspace_advance(no_further_research_needed=true)`.

**Advance 1.1 -> 1.2** requires: `no_further_research_needed=true`, every open research discussion having linked research, at least 1 research entry saved, all entries valid.

---

## Phase 1.2: Research Proving

**Actor**: Prover sub-agent (Opus, one-shot)

### Goal

Verify that every research finding references real, accurate evidence. The prover reads files, checks line numbers, validates commits — it does not research, only verifies.

### Deployment

```
Agent(
  subagent_type: "research-prover",
  prompt: "Verify all research entries for this workspace. Mark each as proven or rejected.
           Workspace: {working_dir}"
)
```

The prover calls `workspace_prove_research` for each entry directly — the orchestrator does NOT need to relay these calls. Its return is the completion notice: ask it for a short proven/rejected list by entry, and do not re-read every research entry yourself.

### Rejection loop

For each rejected entry:

1. Decide whether the topic is still relevant.
2. If relevant: re-deploy the original researcher to fix the proofs or re-investigate, then re-deploy the prover. Repeat until proven.
3. If stale or no longer needed: `workspace_delete_research(id)` (the user can also delete it in the Research tab).
4. After 2 failed re-proof attempts for the same topic, treat it as stale: post a discussion via `workspace_post_discussion` noting the gap and ask the user whether to delete it or provide more context.

Rejected entries block advancement — all entries must be proven or deleted before advancing past 1.2.

### When all research is proven

1. Call `workspace_update_progress` for phase `"1"` with a summary covering: total research entries, topics investigated, any re-investigations needed, and key findings that affect planning.
2. Call `workspace_advance`.

**Advance 1.2 -> 1.3** requires: all research entries proven + progress entry `"1"`.

---

## Phase 1.3: Impact Analysis

**Actors**: Orchestrator + plan-advisor

### Goal

Analyze the proven research findings to identify high-level impacts beyond the immediate code changes. This is where you catch the consequences the ticket doesn't mention — the API contract that breaks, the data pipeline that needs a new field, the team that consumes your output.

Send the plan-advisor a brief prompt before starting:

```
SendMessage(
  to: "plan-advisor",
  content: "We are in phase 1.3 (Impact Analysis). The research is proven.
            I will produce the impact analysis. Please review the proven research
            via workspace_list_research and workspace_get_research, and flag any
            impacts I should ensure I cover."
)
```

### Required analysis structure

Cover all six areas (these are the `workspace_set_impact_analysis` fields). Be specific — "the /api/trades POST response now includes an `auditId` field (string, always present)", not "API changes".

- `affected_flows` — user interactions that change, in terms of what users do, not what code runs.
- `api_changes` — request/response format changes, new/removed endpoints, auth changes.
- `data_flow_changes` — origin and destination of new or changed data (e.g. server-generated vs client-supplied).
- `external_dependencies` — actions outside the codebase: unmanaged DB migrations, infrastructure, other teams, third-party APIs.
- `ticket_gaps` — each ambiguity with the options and your recommended option (with reasoning from research).
- `open_questions` — questions that need user input because code, web, or git research cannot resolve them; raised at 1.4.

### Loop logic

Impact analysis may reveal new gaps that need investigation. If this happens:

1. Post new discussion points via `workspace_post_discussion` (type: `"research"`) for the newly discovered questions.
2. Deploy new researcher sub-agents for those topics (same rules as phase 1.1).
3. Deploy prover to verify the new research (same rules as phase 1.2).
4. Re-analyze with the expanded research base.
5. Repeat until all resolvable questions are resolved.

Questions that cannot be resolved from code, web, or git research are left as open questions for the user at phase 1.4. Do not loop indefinitely — if a question requires a human decision, flag it and move on.

### When analysis is complete

1. Call `workspace_set_impact_analysis` with the six fields above. Within each field, put each distinct item on its own line or as a markdown bullet (`- item`) so the panel renders a readable list rather than a run-on paragraph.

   This data is displayed in the Pre-planning tab for user review at phase 1.4.

2. Call `workspace_update_progress` for phase `"1.3"` summarizing: affected user flows, API changes, data flow changes, external dependencies, ticket gaps with recommendations, and open questions for the user.
3. Call `workspace_advance`.

**Advance 1.3 -> 1.4** requires: progress entry `"1.3"`.

---

## Phase 1.4: Preparation Review (USER GATE)

### Goal

Present the complete preparation to the user for review and approval. The user sees everything discovered during phases 1.0-1.3 and decides whether the foundation is solid enough for planning.

### Presentation

Present to the user via **both** chat and the admin panel pre-planning tab:

**1. Research summaries**
One entry per research topic. Use the `summary` field from each research entry — do not dump full findings. The user can drill into details in the admin panel if needed.

**2. Impact analysis summary**
The six-part analysis from phase 1.3, formatted for readability. Highlight anything that affects scope, timeline, or coordination with other teams.

**3. Open discussions / questions for user**
Questions that could not be resolved from research. Each question should include:
- What was investigated
- What was found (or not found)
- Why a human decision is needed
- Recommended option (if you have one) with reasoning

**4. Resolved discussions**
Discussions that were resolved during research, with brief resolution summaries. This shows the user what was figured out without their input.

### Waiting for approval

Call `workspace_advance` to enter the user gate. When it returns 202, tell the user the gate is waiting and end the turn — do not poll. Re-check `workspace_get_state` once when the user messages or a scheduled check fires; if the phase advanced, proceed to phase 2.0 (Planning).

### On rejection

The user rejected with comments. Their comments guide what needs more work.

1. Read comments via `workspace_get_comments`
2. Determine which phase to revisit:
   - If comments point to missing research -> back to 1.1, deploy researchers for the new topics
   - If comments question the impact analysis -> back to 1.3, re-analyze with user's perspective
   - If comments correct the assessment -> back to 1.0, resume plan-advisor with corrections
3. Re-prove any new research (1.2)
4. Re-analyze impacts if research changed (1.3)
5. Re-present for approval (1.4)

### On approval

Proceed to phase 2.0 (Planning). The preparation is locked — all research, impact analysis, and resolved discussions form the foundation for the execution plan.
