---
name: mcp-tools
description: Authoring MCP tools in the Anthropic-recommended style — annotations, types, error envelopes, registration.
---

# MCP tool authoring

## When to use

Read this before adding a new MCP tool to `admin-panel/backend/mcp_tools/`, renaming one, changing a parameter shape, or materially reworking an error path. The patterns below are load-bearing — tests, the frontend, and the orchestrator all depend on the envelope shape and the tool-annotation contract.

## FastMCP basics

- One shared `FastMCP` instance lives at the bottom of `admin-panel/backend/mcp_tools/__init__.py`:
  ```python
  mcp = FastMCP("workspace", instructions="Workspace state management for orchestrator workflow.")
  ```
- Every tool is a plain Python function decorated with `@mcp.tool(annotations=ToolAnnotations(...))`.
- Tools are grouped into modules by domain (`advance.py`, `comments.py`, `criteria.py`, `plan_scope.py`, `rules.py`, `state.py`, …). Registration happens via side-effecting imports at the bottom of `mcp_tools/__init__.py`:
  ```python
  from mcp_tools import rules  # noqa: F401, E402
  ```
- The MCP process entry point is `admin-panel/backend/mcp_server.py`, which just imports `mcp_tools` and calls `mcp.run()`.

## ToolAnnotations — the four hints

The annotations are the model's optimization hints. Set them honestly — wrong hints cause the orchestrator to mis-route calls.

| Tool pattern                 | readOnlyHint | idempotentHint | destructiveHint | openWorldHint |
| ---------------------------- | ------------ | -------------- | --------------- | ------------- |
| list / get / read            | true         | true           | false           | false         |
| create (server-assigned ID)  | false        | false          | false           | false         |
| create-or-replace (upsert)   | false        | true           | false           | false         |
| update (by ID)               | false        | true           | false           | false         |
| delete / drop                | false        | false          | true            | false         |
| external-system side effect  | false        | (depends)      | (depends)       | true          |

Worked example from `mcp_tools/rules.py`:

```python
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
        openWorldHint=False,
    ),
)
def rule_list(project_id: int) -> list[dict]:
    """List all rule files for a project..."""
```

And from `plan_scope.py` for a destructive delete, contrast with a scope upsert where `idempotentHint=True` (same input produces the same state every time).

## Type hints and Literal types

- MCP auto-derives the JSON Schema from Python type hints. Keep types tight: `int`, `str`, `list[dict]`, `X | None`, etc.
- Use `typing.Literal[...]` for enum-like parameters:
  ```python
  def workspace_resolve_review_issue(
      issue_id: int,
      resolution: Literal["fixed", "false_positive", "out_of_scope"],
  ) -> dict:
      ...
  ```
- Add **runtime validation** too (defense in depth — Literal only enforces at the MCP dispatch layer):
  ```python
  if resolution not in {"fixed", "false_positive", "out_of_scope"}:
      return mcp_error("validation", "invalid_resolution")
  ```
- For richer parameter descriptions exposed to the model, wrap with `Annotated[T, Field(description="...")]`:
  ```python
  def rule_get(
      project_id: int,
      name: Annotated[str, Field(description="Rule name (kebab-case, <= 63 chars)")],
  ) -> dict:
      ...
  ```

## Docstrings as descriptions

- The tool's docstring becomes the description the model reads. Write it imperatively and agent-oriented: **"List all rule files for a project"**, not "Lists all rule files".
- Document each parameter briefly. Call out side effects. Mention when to call and when not to.
- Keep it short — the model costs tokens for every tool description it loads.

## Workspace binding

Two decorators, pick one:

- `@with_mcp_workspace` — for workspace-scoped tools. Auto-detects the workspace from `cwd`, opens a DB connection, injects `(ws, project, db, locale)` as the first four positional args, closes the DB in `finally`. Returns a `not_found` envelope if no workspace is detected.
- `@with_global_db` — for workspace-agnostic tools that still need a DB (`rule_*` tools, for example). Injects `db` as the first arg, closes on exit, rolls back on exception. The tool body MUST call `db.commit()` on its success path — the decorator does NOT auto-commit.

Both decorators strip their injected parameters from the externally visible signature via `inspect.signature`.

## Error envelope

Services raise domain-specific exceptions with stable `code` attributes (e.g. `RuleServiceError(code="rule_not_found")`). The MCP layer translates them into an additive envelope. Three helpers in `mcp_tools/__init__.py`:

- `mcp_error(category, message, retryable=False, details=None)` — the primitive. Categories: `transient`, `validation`, `business`, `permission`, `not_found`.
- `translate_service_error(result, mapping, default_category="business")` — for services that return `{"error": "<key>"}` dicts. Maps keys to `(category, retryable)` tuples.
- `envelope_from_status(result, status_code)` — for services that return `(dict, http_status)` pairs. Known codes map to categories; `>= 500` becomes `transient, retryable=True`.

Return the envelope on known error paths. Let unknown exceptions bubble — FastMCP converts them to protocol-level `isError=True`. Never emit a raw stack trace to the model.

Transient DB failures (`sqlite3.OperationalError`, `sqlite3.DatabaseError`) are the only retryable ones; see `TRANSIENT_DB_EXCEPTIONS`.

## Adding a new tool — step-by-step

1. Pick the right module under `mcp_tools/` by domain. If your tool introduces a new domain, create `mcp_tools/<domain>.py` and add `from mcp_tools import <domain>  # noqa: F401, E402` to `mcp_tools/__init__.py`.
2. Import what you need:
   ```python
   from mcp.server.fastmcp import FastMCP
   from mcp.server.fastmcp.prompts.base import ToolAnnotations
   from . import mcp, mcp_error, with_mcp_workspace  # or with_global_db
   from services import <your_service>
   ```
3. Write the function:
   ```python
   @mcp.tool(
       annotations=ToolAnnotations(readOnlyHint=..., idempotentHint=..., destructiveHint=..., openWorldHint=False),
   )
   @with_mcp_workspace
   def workspace_do_thing(ws, project, db, locale, arg1: int, arg2: str) -> dict:
       """Do a thing. Describe side effects."""
       try:
           result = <your_service>.do_thing(db, ws["id"], arg1, arg2)
       except <DomainError> as e:
           return mcp_error("business", str(e))
       db.commit()
       return result
   ```
4. Add a matching test in `admin-panel/backend/tests/test_mcp_tools.py` — call the function directly (bypassing MCP dispatch), cover the happy path, and cover at least one error path.
5. If your tool introduces a new user-facing message, add the i18n key to `admin-panel/backend/messages/` and reach it via `t(key)`.

## Common pitfalls

- **Omitting `annotations=`**. The model loses every optimization hint. Always set all four fields explicitly.
- **`readOnlyHint=True` on a tool that writes audit rows or logs**. That's not read-only. Mark it `false`.
- **`destructiveHint=True` on create-or-replace upserts**. Upserts are idempotent, not destructive. Use `idempotentHint=True, destructiveHint=False`.
- **Returning `None`**. Always return a `dict` or `list[dict]` with meaningful content. Empty results should be `[]` or `{}`, not `None`.
- **Leaking DB connections**. Let `@with_mcp_workspace` / `@with_global_db` handle `close()`. Don't open your own `get_db()` inside a decorated tool.
- **Catching broad `Exception`**. Catch the specific domain exception, translate it, and let the rest propagate.
- **Forgetting `db.commit()`** in `with_global_db` tools. The decorator does not commit for you.

## Testing checklist

Every tool needs at least:

- A test that calls the tool function directly (not through MCP dispatch).
- Coverage for the happy path — asserts on the returned structure.
- Coverage for one known error path — asserts the envelope shape (`error`, `errorCategory`, `isRetryable`).
- Use the shared DB fixture from `admin-panel/backend/tests/conftest.py`; don't mock the DB.

Run the full suite before merging:

```bash
cd admin-panel/backend && python3 -m pytest tests/ -v --tb=short
```
