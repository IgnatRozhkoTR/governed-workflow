# governed-workflow

Zero-trust orchestration layer for Claude Code — server-side phase gates, scope locking, and human approval. See `README.md` for the full workflow diagram.

## Repo Split

- `admin-panel/` — Flask web app + MCP server that holds workspace state and enforces phase transitions. See `admin-panel/CLAUDE.md`.
- `claude/` — Payload shipped into user workspaces (agents, skills, rules, hooks, modules). See `claude/CLAUDE.md`.

## Core Rule

NEVER commit, push, or create merge requests unless explicitly asked. See subfolder `CLAUDE.md` files for folder-specific instructions.
