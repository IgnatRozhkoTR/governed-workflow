---
name: memory-promotion
description: Convert proven research findings into memory_write proposals.
---

# Memory Promotion Skill

Convert proven research findings into pending memory_write proposals that an admin can approve via the Proposals tab.

## When to invoke

Invoke this skill after phase 1.2 research has been marked proven (`workspace_prove_research`). It can also be invoked manually at any point to re-scan all proven entries and emit proposals for any findings not yet promoted.

## What it does

Calls the MCP tool `memory_promotion_run` on the governed-workflow server. The tool:

1. Loads all research entries for the current workspace where `proven = 1`.
2. Iterates every finding in those entries and classifies each as project-level or ticket-specific (see heuristic below).
3. For project-level candidates, calls the LLM to confirm broad applicability.
4. Checks for near-duplicate memories already stored (dedup step).
5. Emits a `memory_write` proposal for each surviving finding.
6. Returns counts and proposal IDs.

## Classification heuristic

A finding is treated as project-level if any of the following is true:

- Its `proof.files` list contains more than 2 entries (spans multiple files).
- Its title or body contains architecture/convention keywords: `architecture`, `architectural`, `convention`, `pattern`, `across the codebase`, `throughout the project`.
- Its normalized title appears in 2 or more distinct research entries for the same workspace.

Findings that do not meet any criterion are ticket-specific and are skipped.

## LLM gate

Each project-level candidate is sent to the LLM with the prompt:

```
Is the following finding broadly applicable to future tickets in this codebase, beyond the current ticket? Answer YES or NO with one-sentence justification.
```

Findings where the LLM responds NO are skipped.

## Dedup step

Before creating a proposal the tool calls `memory_service.retrieve` with the finding title as the query and a project-scoped filter. If any result has a relevance score above 0.85 the finding is considered already stored and is skipped.

## Approval required

No memories are written until a human approves the resulting proposals via the admin panel Proposals tab. The tool only creates `pending` proposals.

## Usage

```
/memory-promotion
```

No arguments are required. The workspace is inferred from the MCP connection context.

## Behavior notes

This is a skill, not a declarative phase. Orchestrators must invoke it explicitly — it is not triggered automatically by phase transitions.
