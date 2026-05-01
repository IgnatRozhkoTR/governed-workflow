---
name: reflection
description: Generate a post-task reflection report from the current Claude Code session.
---

# Reflection Skill

Generate a structured reflection report at the end of a task. The report is saved to the admin panel and a one-line summary is printed to the console.

## When to Invoke

Invoke this skill when a task is substantially complete — typically near phase 5 (Done) or when the user explicitly requests a retrospective. It can also be invoked manually at any point to capture an intermediate checkpoint.

## What It Does

Calls the MCP tool `reflection_run` on the governed-workflow server. The tool:

1. Reads the current session transcript and workspace state.
2. Asks the LLM to produce a Markdown reflection covering: what was done, decisions made, trade-offs, open questions, and next steps.
3. Persists the report to the admin panel database with a short summary line.
4. Returns the report ID and summary.

## Usage

```
/reflection
```

No arguments are required. The workspace is inferred from the MCP connection context.

## Output

- A Markdown report visible in the admin panel under the Reflection tab.
- A summary line printed to the console: `Reflection #<id> saved: <summary>`.

## Behavior Notes

- **v1 scope**: The skill only writes a reflection report. Proposal emission (automatically surfacing improvement suggestions back into the workflow) is planned for v3.5 and is not present here.
- If no active session is found (HTTP 409 from the API), the skill prints an error and stops.
- If the LLM provider is not configured (HTTP 503), the skill prints a setup hint and stops.
