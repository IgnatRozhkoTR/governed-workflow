# governed-workflow

Zero-trust orchestration layer for Claude Code — server-side phase gates, scope locking, and human approval. See `README.md` for the full workflow diagram.

## Repo Split

- `admin-panel/` — Flask web app + MCP server that holds workspace state and enforces phase transitions. See `admin-panel/CLAUDE.md`.
- `claude/` — Payload shipped into user workspaces (agents, skills, rules, hooks, modules). See `claude/CLAUDE.md`.

## Core Rule

NEVER commit, push, or create merge requests unless explicitly asked. See subfolder `CLAUDE.md` files for folder-specific instructions.


---

# Governed Workflow Defaults

# claude

Payload shipped into user workspaces by the installer — Claude Code extensions that make the governed workflow function.

## Folder Map

- `agents/` — 16 specialized agent role definitions. See `agents/CLAUDE.md`.
- `skills/` — 9 slash-command skills (governed-workflow, plan-preparation, planning, setup, rules, telegram-multi-session, commit-push-mr, local-review, chrome-troubleshooter). See `skills/CLAUDE.md`.
- `rules/` — Default Markdown rule files with YAML frontmatter; auto-loaded by Claude Code based on `paths` globs.
- `modules/` — Self-contained feature packages (currently `telegram/` for remote session control).
- `hooks/` — Claude Code hooks: `pre-tool-hook.py`, `session-start.py`, `block-orchestrator-writes.py`, `user-prompt-submit.sh`.
- `defaults/` — Templates copied into workspaces: `git-rules.md`, `git-hooks/`, `.mcp-funnel.json`.
- `tools/` — Verification binaries (ktlint, google-java-format, pmd).

See `README.md` for how the payload is installed into a workspace.
