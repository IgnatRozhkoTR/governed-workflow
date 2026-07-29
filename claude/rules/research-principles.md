---
name: research-principles
description: Evidence-based research guidance — verify, be thorough, and establish context. Applies broadly when reading or searching code.
paths:
  - "**/*"
---

# Research Principles

## Core Principles
Verify: Always examine actual evidence (code, commits, pages, DOM).
Thorough: Follow every lead, cross-check, dig until complete understanding.
Context: Understand bigger picture, not isolated facts.

## Research Tools
| Tool | Purpose |
|------|---------|
| Grep | Pattern search (keywords, annotations) |
| Glob | Find files (**/*.java, **/test/*.py) |
| Read | Examine file contents |
| LS | Directory structure |

## Code Research Strategy
1. Entry points > execution path > data flow
2. Search variations: classes, methods, interfaces, annotations, imports
3. Check tests for behavior, configs for setup

## Reporting
Include:
- Exact references (file:line)
- Context and connections
- Patterns identified
- Limitations of findings

## Absence Claims
Any claim of the form "there is no X in this codebase" must state the search you ran (the exact grep/glob pattern and the paths covered). Unverified absence claims are the single most common failure mode in this workflow.
