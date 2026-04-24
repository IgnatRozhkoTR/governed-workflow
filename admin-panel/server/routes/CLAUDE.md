# routes

Flask HTTP handlers. One Blueprint per domain, registered by `app.py`.

## Conventions

- Use `@with_workspace` and `@with_project` decorators from `core.decorators` to resolve path-scoped context and bind a DB connection.
- All responses are JSON.
- Routes are thin — delegate logic to the corresponding service in `services/`.
- Workspace endpoints are scoped under `/api/ws/<project_id>/<branch>/`.
- WebSocket routes (terminal, setup, LSP) use `flask-sock`.
