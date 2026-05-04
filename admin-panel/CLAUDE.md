# admin-panel

Flask web app + MCP stdio server. Holds workspace state and enforces phase/scope rules. Serves at `http://localhost:5111`. Run with `python3 backend/app.py`. SQLite DB auto-created at `backend/admin-panel.db` on first run.

## Tech Stack

- Backend: Flask + SQLite (Yoyo migrations)
- Frontend: vanilla JS SPA, no framework
- Agent interface: MCP over stdio (`backend/mcp_server.py`)

## Layer Map

- `backend/` — routes, services, MCP tools, advance/phase logic. See `backend/CLAUDE.md`.
- `frontend/` — single `admin.html` + modular JS/CSS/i18n. See `frontend/CLAUDE.md`.
- `core/llm_client.py` — LLM wrapper; reads `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`, model from `GW_REFLECTION_MODEL`.
- `services/work_mode_service.py` — work mode CRUD; REST-only by design (no MCP tools).
- `services/phase_settings.py`, `phase_resolver.py` — DB-driven phase toggle; replaced the previous `ALWAYS_ON_PHASE_IDS` frozenset.
- `services/reflection_service.py` + `session_extractor.py` — post-task LLM report + proposal emission.
- `services/memory_provider.py`, `mempalace_adapter.py`, `memory_service.py` — abstract memory interface + MemPalace.
- `services/proposal_service.py`, `proposal_executor.py` — approval-gated change queue; 9 proposal types.
- `services/memory_promotion_service.py` — research-to-memory heuristic + LLM gate + dedup.

## MCP tool surface

53 tools: `workspace_*`, `research_*`, `criteria_*`, `plan_*`, `scope_*`, `progress_*`, `rules_*`, `comments_*`, `verification_*`, `improvements_*`, `reflection_*` (3), `memory_*` (5), `proposal_*` (6), `memory_promotion_run` (1).
