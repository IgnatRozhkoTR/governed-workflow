---
name: scratchpad
description: Write human-facing reports and explanations (e.g. "explain this PR", "summarize this job") as markdown files, separate from the actual code changes.
user_invocable: false
---

# Scratchpad Skill

When you produce a report, explanation, or summary meant for the human to read separately from the code changes themselves — not something that becomes part of the diff/PR — write it as a markdown file rather than only answering in chat.

## Where to write

Use your normal file tools (Write/Edit), no special MCP tool. Write into:

```
.claude/scratchpad/<descriptive-kebab-name>.md
```

Start the file with a `# ` H1 — it becomes the report's title in the admin panel UI.

## Multi-repo workspaces

- A report about one specific attached repo (e.g. "explain the PR you just opened in `service-a`") goes into that repo's own `.claude/scratchpad/`.
- A report spanning the whole job/workspace (e.g. "summarize everything this job did") goes into the workspace root's own `.claude/scratchpad/` — the composite directory's, not any individual attached repo's.

## Examples

- "Explain every PR you just created" → one `pr-explainer.md` per repo that has a PR, written into that repo's `.claude/scratchpad/`.
- "Summarize this job's outcome" → `job-summary.md` in the workspace root's `.claude/scratchpad/`.

This is a lightweight convention, not a workflow — no approval gate, no MCP tool, just a fixed, predictable place for human-facing writeups.
