---
name: python
description: Python conventions for this repo — style, imports, domain exceptions, DB access, tests.
paths:
  - "admin-panel/**/*.py"
  - "claude/**/*.py"
  - "**/*.py"
---

# Python conventions

## Style

- Python 3.10+. Use `X | None` union syntax, not `Optional[X]`.
- Type hints required on public service functions, Flask routes, and MCP tool signatures. Optional on internal helpers when type is obvious.
- `snake_case` for functions and variables, `PascalCase` for classes, `UPPER_SNAKE` for module constants.
- Functions stay around 30 lines or less. When longer, extract named helpers.
- No `TODO` / `FIXME` comments. Implement or delete.
- No placeholder returns (no `return True` where real logic belongs).
- No technical comments explaining HOW code works. Only WHY comments for non-obvious business logic.

## Imports

- Three groups, one blank line between: stdlib, third-party, local.
- No wildcard imports.
- Module-level side-effect imports (`from mcp_tools import state  # noqa: F401, E402`) belong at the bottom with an explicit suppression comment.

## Exceptions

- Services raise domain-specific exceptions with a stable `code` attribute (e.g. `RuleServiceError(code="rule_not_found")`). Never raise generic `Exception`.
- Route layer maps `exception.code -> HTTP status` via a small dispatch map and returns `({"error": "..."}, status)`.
- MCP tool layer wraps the same domain exceptions via `translate_service_error` / `envelope_from_status` into the `mcp_error` envelope.
- Only one broad catch is intentional: the top-level `@app.errorhandler(Exception)` in `app.py` acts as Flask's last-resort handler. Anywhere else, catch specific types only.
- `TRANSIENT_DB_EXCEPTIONS` (`sqlite3.OperationalError`, `sqlite3.DatabaseError`) are the only retryable exceptions in MCP tools.

## Database

- Always get connections via `get_db()` (or `get_db_ctx()` context manager) from `core.db`. Row factory is set; `PRAGMA foreign_keys = ON`, WAL mode, and `busy_timeout` are applied.
- Explicit `db.commit()` on the success path. Decorators do NOT auto-commit.
- Always close in `finally` (or use `get_db_ctx()`).
- Rollback on exception, then re-raise.
- SQL parameters use `?` placeholders. Never f-string or `%`-format values into SQL.

## MCP tools

- Signatures use `Annotated[T, Field(description="...")]` for rich parameter descriptions exposed to the agent.
- `Literal[...]` for enum-like strings (resolutions, severities, statuses). Re-check at runtime with an explicit `if value not in {...}: raise ...` for defense in depth.
- Wrap each tool with `@with_mcp_workspace` (workspace-scoped) or `@with_global_db` (workspace-agnostic).
- Known error paths return `mcp_error(category, message, retryable=..., details=...)`. Unexpected exceptions propagate so FastMCP sets `isError=True`.
- Add `ToolAnnotations(readOnlyHint=..., idempotentHint=..., destructiveHint=..., openWorldHint=...)` on every tool. See `.claude/skills/mcp-tools/SKILL.md`.

## Flask routes

- One Blueprint per domain in `routes/`.
- Use `@with_workspace` / `@with_project` decorators from `core.decorators` for scoped endpoints.
- Always return JSON. For errors, return `({"error": "..."}, <status>)`.
- Keep route handlers thin — delegate to services.

## Tests

- Real SQLite (fresh tmp DB from `conftest.py`) — never mock the DB.
- Function naming: `test_<behavior>_<condition>` (e.g. `test_create_rule_succeeds_when_name_valid`).
- Test the service layer, REST layer, and MCP layer each in their own files / sections.
- Arrange / act / assert with blank lines between sections.
- No placeholder assertions. Every test makes meaningful claims about behavior.
