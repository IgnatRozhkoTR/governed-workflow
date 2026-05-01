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

## Sub-phase 3.7 additions

New services: `reflection_service`, `session_extractor`, `memory_provider`, `mempalace_adapter`, `memory_service`, `proposal_service`, `proposal_executor`, `agent_service`, `skill_service`, `_md_frontmatter`, `memory_promotion_service`, `work_mode_service`. Modified: `phase_settings`, `phase_resolver`. New MCP tool families: `reflection_*` (3), `memory_*` (5), `proposal_*` (6), `memory_promotion_run` (1), `work_mode_*` (6) — 21 new, total 38 → 59. Migrations 0027-0030. Tabs: Reflection, Memory, Proposals, Work Modes. LLM client: `core/llm_client.py` (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`, model from `GW_REFLECTION_MODEL`).
