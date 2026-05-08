# services

Domain CRUD layer. One file per domain (comment, criteria, discussion, git_rules, improvement, lsp, plan, progress, research, rule, scope, verification, phase_settings, modules_discovery, module_phase_loader, phase_resolver, phase_sequencer).

## Conventions

- Each service takes `(db, ...)` and returns plain dicts (not ORM objects).
- Services are called by both `routes/` (HTTP) and `mcp_tools/` (MCP stdio) — they are the shared business layer.
- Services do not open the DB themselves; the caller does, and always closes in `finally`.
- Domain-specific errors raise subclasses of a service-level exception; routes and MCP tools translate them to HTTP status / MCP error envelope.

## Adding a memory provider

1. Create an adapter module implementing `MemoryProvider` (see `mempalace_adapter.py` as the reference).
2. At the bottom of the adapter module, call `register_provider("<module_id>", lambda: <constructor>())` — this runs once at import time.
3. Enable the module by inserting its `module_id` into the `modules_enabled` table via the Setup page.
4. `memory_service._provider(db)` queries `modules_enabled` and calls `get_active_provider`, which returns the first registered provider whose name appears in the enabled list.
