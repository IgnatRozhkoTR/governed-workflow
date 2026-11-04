---
name: token-efficiency
description: Step and context discipline for every agent — fewer turns and smaller tool output, same work. Adapted from JetBrains benjamin-plus.
paths:
  - "**"
---

# Token efficiency

Every turn re-reads the whole conversation, so cost is steps × context, not words. Save by taking fewer steps and keeping bulky output out of the transcript — never by doing less work. These rules change how you look things up, wait, and report, not what you build, research, or review. If saving a step risks a wrong result, spend the step.

## 1. Recon in one pass

Collect every independent fact in one step: several tool calls in one message (Read/Grep/Glob, or workspace reads such as `workspace_get_state` + `workspace_get_plan` together), or chained shell probes with labelled sections (`echo "== layout =="; ls; echo "== build =="; head -40 pom.xml`). A second round is only for questions the first round raised. Before copying a convention (a DSL, schema, file format, test style), sample two existing examples of the exact construct, not one.

## 2. Look through a keyhole

Inspection ends with a limiter: `| head -50`, `| tail -20`, `grep -m 20`, `wc -l` before contents, Read with offset/limit, Grep with `head_limit` or `files_with_matches`. Size unknown? Measure first, then read the slice you need. Read a file whole only when you will edit it, copy from it, or it is the thing under review. If a peek was too narrow, take exactly one wider look. Don't re-fetch what is already in your context and hasn't changed — a file you just wrote, state you read this turn.

## 3. Probe the environment once

Before running builds or tests with several prerequisites, check them together (`command -v java mvn node docker`, one dependency listing) and fix everything missing in one go — never one failure at a time.

## 4. Done means the defined check passes

If the task or the workspace verification profile names a check, run it exactly as written; green means exit status zero. An environmental failure (missing tool, compiler, service) is still yours to fix or report — "unrelated to my change" is not green. The same check failing twice on the same approach means the approach is wrong: name one alternative and try it before patching the next symptom. When the check passes, stop — no victory-lap re-reads of files you just wrote. Don't build harnesses, scripts, or checkers nobody asked for.

## 5. Waiting is a step

A running command or background agent that hasn't finished has nothing new to say. Background agents and background commands notify you when they complete — don't poll them. When you must check, wait in large slices (30 s or more; minutes for builds and test suites), never in tight loops.

## 6. Report conclusions, not dumps

Follow your role's report format; within it, cite `file:line` and state the facts that matter instead of pasting file contents or full logs. When delegating, ask for exactly the output you need. Don't restate what a sub-agent or tool already returned, and don't narrate steps you are about to take.
