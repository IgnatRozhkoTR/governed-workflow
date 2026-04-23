# Core

Foundation layer — no business logic, no domain imports. Everything else depends on core, core depends on nothing in the server package.

- `db.py` — SQLite connection and startup bootstrap; applies Yoyo migrations from `server/migrations/`
- `helpers.py` — path utilities, git subprocess wrapper, scope pattern matching
- `i18n.py` — translation with locale fallback (message files live in `server/messages/`)
- `paths.py` — repo/home path resolution used by setup and workspace install
- `phase.py` — `phase_key()` function returning a comparable tuple from a dotted-string phase identifier
- `terminal.py` — tmux session management, PTY-WebSocket bridge
- `decorators.py` — Flask route decorators (`with_workspace`, `with_project`)
- `global_flags.py` — process-wide feature toggles read by routes and MCP tools
