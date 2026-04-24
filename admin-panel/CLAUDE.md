# admin-panel

Flask web app + MCP stdio server. Holds workspace state and enforces phase/scope rules.

## Run

```bash
python3 server/app.py
```

Serves at http://localhost:5111. SQLite DB auto-created at `server/admin-panel.db` on first run.

## Tech Stack

- Backend: Flask + SQLite (Yoyo migrations)
- Frontend: vanilla JS SPA, no framework
- Agent interface: MCP over stdio (`server/mcp_server.py`)

## Layer Map

- `server/` — backend (routes, services, MCP tools, advance/phase logic). See `server/CLAUDE.md`.
- `templates/` — frontend (single `admin.html` + modular JS/CSS/i18n). See `templates/CLAUDE.md`.

See subfolder `CLAUDE.md` files for details on each layer.
