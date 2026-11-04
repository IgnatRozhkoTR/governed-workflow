#!/usr/bin/env python3
"""PreToolUse hook: denies naming a sub-agent spawn unless it is plan-advisor.

Claude Code 2.1.281: an `Agent` call WITH `name` spawns an in-process
teammate whose tools are intersected with the orchestrator's own tool
allowlist — the teammate loses any tool the orchestrator itself cannot call
(e.g. MCP workspace tools, Edit/Write). An `Agent` call WITHOUT `name`
spawns a plain one-shot sub-agent that keeps its full frontmatter tool list.

Only plan-advisor is meant to run as a resumable named teammate. Every other
agent type must be spawned without `name`.
"""
import json, sys

data = json.load(sys.stdin)

if data.get("tool_name", "") != "Agent":
    sys.exit(0)

tool_input = data.get("tool_input", {})
name = tool_input.get("name")
subagent_type = tool_input.get("subagent_type")

if not name:
    sys.exit(0)

if subagent_type == "plan-advisor":
    sys.exit(0)

json.dump({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"Spawn {subagent_type or 'this agent'} without `name`: named spawns become "
            "teammates restricted to the orchestrator's tools, so the agent loses its MCP "
            "tools. Only plan-advisor is spawned by name."
        )
    }
}, sys.stdout)

sys.exit(0)
