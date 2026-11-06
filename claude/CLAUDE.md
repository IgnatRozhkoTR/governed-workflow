# claude

Payload shipped into user workspaces by the installer — Claude Code extensions that make the governed workflow function.

## Folder Map

- `agents/` — 23 agent definitions — the orchestrator plus 22 sub-agent roles it works with. See `agents/CLAUDE.md`.
- `skills/` — 9 slash-command skills (governed-workflow, plan-preparation, planning, setup, rules, module-installation, commit-push-mr, local-review, chrome-troubleshooter). See `skills/CLAUDE.md`.
- `rules/` — Default Markdown rule files with YAML frontmatter; auto-loaded by Claude Code based on `paths` globs.
- `modules/` — Self-contained feature packages (none ship by default; per-device modules live in `modules-local/`).
- `hooks/` — Claude Code hooks: `pre-tool-hook.py`, `session-start.py`, `block-orchestrator-writes.py`, `user-prompt-submit.sh`.
- `defaults/` — Templates copied into workspaces: `git-rules.md`, `git-hooks/`, `.mcp-funnel.json`.
- `tools/` — Verification binaries (ktlint, google-java-format, pmd).

See `README.md` for how the payload is installed into a workspace.
