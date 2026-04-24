# server

Flask + MCP backend. Both entry points (`app.py` for HTTP, `mcp_server.py` for MCP stdio) delegate to the same services.

## Layer Map

- `core/` — infrastructure (db, paths, helpers, phase key, i18n, terminal, decorators). No business logic.
- `services/` — domain CRUD, one file per domain.
- `routes/` — Flask Blueprints, one per domain.
- `mcp_tools/` — MCP tool implementations.
- `advance/` — phase definitions, phase-gate orchestration, guards, permissions.
- `migrations/` — Yoyo SQL migrations applied on startup.
- `messages/` — i18n catalogs (en, ru).
- `tests/` — pytest suite.

## Key Patterns

- `get_db()` returns a sqlite3 connection with Row factory and foreign keys ON. Always close in `finally`.
- State lives entirely in SQLite (`admin-panel.db`). No lock files.
- `find_workspace(db, project_id, branch)` handles branch sanitization automatically.

See `advance/CLAUDE.md` and `mcp_tools/CLAUDE.md` for the complex subsystems.
