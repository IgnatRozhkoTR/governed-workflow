# claude

Payload shipped into user workspaces by the installer — Claude Code extensions that make the governed workflow function.

## Folder Map

- `agents/` — 20 agent definitions — the orchestrator plus 19 sub-agent roles it works with. See `agents/CLAUDE.md`.
- `skills/` — 10 slash-command skills (governed-workflow, plan-preparation, planning, setup, rules, module-installation, telegram-multi-session, commit-push-mr, local-review, chrome-troubleshooter). See `skills/CLAUDE.md`.
- `rules/` — Default Markdown rule files with YAML frontmatter; auto-loaded by Claude Code based on `paths` globs.
- `modules/` — Self-contained feature packages (currently `telegram/` for remote session control).
- `hooks/` — Claude Code hooks: `pre-tool-hook.py`, `session-start.py`, `block-orchestrator-writes.py`, `user-prompt-submit.sh`.
- `defaults/` — Templates copied into workspaces: `git-rules.md`, `git-hooks/`, `.mcp-funnel.json`.
- `tools/` — Verification binaries (ktlint, google-java-format, pmd).

See `README.md` for how the payload is installed into a workspace.
