---
name: workflow-hardening
description: Admin boundary rules for orchestrator sessions — no direct API calls, no self-approval, no hook bypass.
paths:
  - "**"
---

# Workflow hardening

## Admin boundary

Never fetch, print, store, or use admin authentication tokens.
Never call protected admin HTTP APIs directly (no curl, wget, fetch, urllib, requests against localhost:5111 or any governed-workflow admin URL).
Never approve or reject gates yourself.
Use MCP workspace tools only.
If blocked by phase, scope, auth, or hook rules, report the blocker to the user and wait. Do not try to work around it.
Do not attempt to bypass hooks or admin-panel enforcement. Hooks are user-level guardrails; bypassing them is a violation.
