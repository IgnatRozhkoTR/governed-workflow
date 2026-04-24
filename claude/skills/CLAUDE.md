# skills

Claude Code slash-command skills. Each subfolder is one skill, invoked as `/<folder-name>` from Claude Code.

## Current Skills

`governed-workflow`, `plan-preparation`, `planning`, `setup`, `rules`, `telegram-multi-session`, `commit-push-mr`, `local-review`, `chrome-troubleshooter`.

## Structure

Each skill folder contains:

- `SKILL.md` — skill spec with YAML frontmatter (`name`, `description`) and the body Claude Code executes when the slash command runs.
- Optional subfolders for nested subskills (e.g. `rules/install/SKILL.md`) — invoked as `/skill subskill`.
- Optional supporting files (`server.ts`, helper scripts) colocated with the skill.

Skills are discovered by Claude Code at session start. The `description` is what the harness sees when deciding whether to invoke the skill.
