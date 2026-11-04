---
name: scratchpad
description: Write human-facing reports and explanations (e.g. "explain this PR", "summarize this job") via the scratchpad MCP tools, separate from the actual code changes.
user_invocable: false
---

# Scratchpad Skill

When you produce a report, explanation, or summary meant for the human to read separately from the code changes themselves — not something that becomes part of the diff/PR — create it as a scratchpad, not a chat-only answer.

## How to write

Use the `scratchpad_create` / `scratchpad_replace` / `scratchpad_patch` / `scratchpad_delete` MCP tools — never Write/Edit, and never a file in `/tmp` or a sub-agent spawned just to write one.

Start `content` with a `# Title` H1 — it becomes the report's title in the admin panel's Scratchpads tab.

Pass `repo` to scope a report to one attached repo in a multi-repo workspace (e.g. "explain the PR you just opened in `service-a`"); omit it for a report spanning the whole job/workspace.

Include a small Mermaid diagram only if it genuinely clarifies a multi-step process or cross-service flow — skip it for simple reports.
