# Claude Payload

Everything under `claude/` is the payload shipped into user workspaces by the installer — the Claude Code extensions that make the governed workflow function.

The top-level slash-command skills are `/governed-workflow`, `/plan-preparation`, `/planning`, `/setup`, `/rules`, `/telegram-multi-session`, `/commit-push-mr`, `/local-review`, and `/chrome-troubleshooter`.

The `agents/` directory includes a `reflector` agent used during phase 5.1 (Reflection). It receives the full reflection context from the orchestrator, analyses the session, and submits improvement proposals via `workspace_submit_proposal`.

The workflow-migration skill syncs `claude/` into a target workspace's `.claude/` directory. Rule files are picked up automatically by Claude Code; agents and skills register as slash commands; hooks register via `settings.json`.
