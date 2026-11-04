# admin-panel

Flask web app + MCP stdio server. Holds workspace state and enforces phase/scope rules.

## Run

```bash
python3 backend/app.py
```

Serves at http://localhost:5111. SQLite DB auto-created at `backend/admin-panel.db` on first run.

## Tech Stack

- Backend: Flask + SQLite (Yoyo migrations)
- Frontend: vanilla JS SPA, no framework
- Agent interface: MCP over stdio (`backend/mcp_server.py`)

## Layer Map

- `backend/` — backend (routes, services, MCP tools, advance/phase logic). See `backend/CLAUDE.md`.
- `frontend/` — frontend (single `admin.html` + modular JS/CSS/i18n). See `frontend/CLAUDE.md`.

See subfolder `CLAUDE.md` files for details on each layer.

## Review house conventions

Optional per-project file `<project>/.claude/rules/review-house-conventions.md`. The 4.0 review pipeline reads it once per run and appends it to every file-reviewer and integration-reviewer prompt as accepted patterns that must not be reported. Absent file means no change. Entries are short, project-specific lines, e.g. "Repositories deliberately return nullable values instead of Optional" or "Mock-only tests do not need repository factory helpers".
