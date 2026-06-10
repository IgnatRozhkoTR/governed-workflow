# services

Domain CRUD layer. One file per domain (comment, criteria, discussion, git_rules, lsp, plan, progress, research, rule, scope, verification, phase_settings, modules_discovery, module_phase_loader, phase_resolver, phase_sequencer).

## Conventions

- Each service takes `(db, ...)` and returns plain dicts (not ORM objects).
- Services are called by both `routes/` (HTTP) and `mcp_tools/` (MCP stdio) — they are the shared business layer.
- Services do not open the DB themselves; the caller does, and always closes in `finally`.
- Domain-specific errors raise subclasses of a service-level exception; routes and MCP tools translate them to HTTP status / MCP error envelope.
