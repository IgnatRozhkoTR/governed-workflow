# Workspace Control

Admin panel for managing scope-locked orchestrator workspaces.

## Running

```bash
python3 server/app.py
```

Runs on http://localhost:5111. DB auto-created at `server/admin-panel.db` on first run.

## Structure

```
server/
  app.py                — Flask app factory, entry point
  mcp_server.py         — MCP stdio entry point (thin bootstrap, tools live in mcp_tools/)
  core/                 — Infrastructure (db, paths, helpers, phase key, i18n, terminal, decorators)
  advance/              — Phase gate subsystem
    orchestrator.py     — perform_advance, approve_gate, reject_gate, transition_phase
    guards.py           — Cross-cutting AdvanceGuard classes
    permissions.py      — Tool permission enforcement per phase
    validators.py       — Acceptance-criteria validators
    phases/             — Phase ABC + concrete definitions (preparation, planning, execution, finalization, declarative)
  services/             — Domain CRUD (comment, criteria, discussion, improvement, lsp, plan, progress, research, rule, scope, verification, module_phase_loader, modules_discovery, phase_resolver, phase_sequencer, phase_settings)
  mcp_tools/            — MCP tool implementations (advance, comments, criteria, improvements, plan_scope, progress, research, rules, state, verification)
  routes/
    advance.py          — Approve/reject user gates
    comments.py         — Comment + discussion CRUD
    context.py          — Workspace context, discussions
    criteria.py         — Acceptance criteria CRUD
    files.py            — File read + git diff
    git_config.py       — Git config management
    history.py          — Phase history rename/undo/squash
    hook_api.py         — Pre-tool hook API (check-permission, session-context)
    hooks.py            — Session-start hook
    improvements.py     — Global improvement CRUD
    lsp.py              — Language-server profiles + lifecycle + WebSocket
    modules.py          — Module discovery and enablement
    phase_settings.py   — Device/project/workspace phase toggles
    projects.py         — Project CRUD
    rules.py            — Project-scoped Markdown rule files (CRUD)
    setup.py            — Setup-skill launcher + WebSocket
    state.py            — Phase, scope, plan, progress endpoints
    static.py           — Serves templates/
    terminal_routes.py  — Embedded terminal (tmux + xterm.js + WebSocket)
    verification.py     — Verification profiles, steps, results
    workspaces.py       — Workspace + branch management
  migrations/           — Yoyo-style SQLite migrations
  messages/             — i18n JSON bundles (en, ru)
  tests/                — pytest suite
templates/
  admin.html            — Single-page UI
  css/                  — Modular stylesheets
  js/                   — Vanilla JS modules
  i18n/                 — Frontend translations
```

## Key Patterns

- `get_db()` returns sqlite3 connection with Row factory and foreign keys ON. Always close in `finally`.
- State lives in SQLite (`admin-panel.db`). No lock files. Phase, scope, plan stored as DB columns.
- `workspace_dir(project_path, branch)` resolves `<project>/.claude/workspaces/<sanitized_branch>/`
- `find_workspace(db, project_id, branch)` handles branch sanitization automatically.
- `GET /api/ws/<project>/<branch>/state` returns full workspace payload: lock, comments, plan, research, phaseHistory.

## Frontend

Vanilla JS, no framework. Global state: `LOCK_DATA`, `PLAN_DATA`, `RESEARCH_DATA`, `DIFF_DATA`, `COMMENTS`.
Comments keyed by `scope:target` in memory. Phases: 0 Init, 1.0 Assessment, 1.1 Research, 1.2 Research Proving, 1.3 Impact Analysis, 1.4 Preparation Review gate, 2.0 Planning, 2.1 Plan Review gate, 3.N.0-3.N.4 Execution sub-phases, 4.0-4.2 Review phases, 5 Done.
