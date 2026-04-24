# Claude Payload

Everything under `claude/` is the payload shipped into user workspaces by the installer. It contains the Claude Code extensions that make the governed workflow function.

## What Lives Here

| Folder | Purpose |
|--------|---------|
| `agents/` | 16 specialized agent role definitions (orchestrator, researchers, engineers, validators, reviewers, plan-advisor). Minimal-tool; rules auto-apply via path globs. |
| `skills/` | 9 slash-command skills: `/governed-workflow`, `/plan-preparation`, `/planning`, `/setup`, `/rules`, `/telegram-multi-session`, `/commit-push-mr`, `/local-review`, `/chrome-troubleshooter`. Each has a `SKILL.md` with frontmatter. |
| `rules/` | Default Markdown rule files (coding-standards, test-standards, validation-pipeline, research-principles, java-conventions). YAML frontmatter declares `paths` globs — Claude Code auto-loads them when matching files are touched. |
| `modules/` | Self-contained feature packages. Currently ships `telegram/` for multi-session Telegram remote control. |
| `hooks/` | Claude Code hook scripts: `pre-tool-hook.py` (scope/phase enforcement), `session-start.py` (registration + context banner), `block-orchestrator-writes.py` (forbid direct orchestrator edits), `user-prompt-submit.sh` (role enforcement). |
| `defaults/` | Templates copied into a workspace on install: `git-rules.md`, `git-hooks/`, `.mcp-funnel.json`. |
| `tools/` | Binaries used by verification profiles (ktlint, google-java-format, pmd). |

## How It Ships

The workflow-migration skill syncs `claude/` into a target workspace's `.claude/` directory. Rule files are picked up automatically by Claude Code; agents and skills register as slash commands; hooks register via `settings.json`.

See subfolder `CLAUDE.md` files for folder-specific pointers.
