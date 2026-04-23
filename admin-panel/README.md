# Workspace Control

The admin panel and MCP server for the [governed workflow](../README.md). Flask web application that manages workspaces, enforces phase transitions, and provides the MCP tools agents interact with. See the root README for the workflow overview and diagram.

## Architecture

| Layer | Details |
|-------|---------|
| Backend | Flask with Blueprints (20 route modules) |
| Frontend | Vanilla HTML/CSS/JS (36 JS modules, 21 CSS modules) |
| Storage | SQLite (`server/admin-panel.db`) |
| Agent Interface | MCP server over stdio (`server/mcp_server.py`, 38 tools) |
| i18n | JSON message bundles (`server/messages/`) |
| Tests | pytest suite (`server/tests/`, 27 test modules) |

## Getting Started

### Prerequisites

- Python 3.10+
- `pip` or a virtual environment manager

### Install

```bash
cd <repo>/admin-panel
python3 -m venv .venv
source .venv/bin/activate
pip install flask mcp flask-sock
```

### Run

**Option A -- launch script** (starts server in background, opens browser):

```bash
cd <repo>/admin-panel
chmod +x start.sh
./start.sh
```

**Option B -- direct**:

```bash
cd <repo>/admin-panel/server
python3 app.py
```

The server starts at http://localhost:5111. The SQLite database is created automatically on first run.

### MCP Server

Add to your `.mcp.json` (use absolute expanded paths — no `~` or `$HOME`):

```json
{
  "mcpServers": {
    "workspace": {
      "command": "/absolute/path/to/governed-workflow/admin-panel/.venv/bin/python3",
      "args": ["-m", "mcp_server"],
      "cwd": "/absolute/path/to/governed-workflow/admin-panel/server"
    }
  }
}
```

## File Structure

```
admin-panel/
  CLAUDE.md                     # Project instructions for Claude Code
  README.md                     # This file
  start.sh                      # Launch script (background server + browser)
  scripts/
    update-proof-snippets.py    # Maintenance utility
  server/
    app.py                      # Flask app factory, entry point
    mcp_server.py               # MCP stdio entry point (thin bootstrap)
    requirements.txt            # Python dependencies
    admin-panel.db              # SQLite database (created on first run)
    core/                       # Infrastructure layer
      db.py                     # SQLite connection, migrations bootstrap
      paths.py                  # Filesystem roots, workspace paths
      helpers.py                # Shared utilities: workspace_dir(), run_git(), match_scope_pattern()
      phase.py                  # Phase key parsing and comparison
      i18n.py                   # Message catalog loader
      decorators.py             # Request decorators (locale, DB binding)
      global_flags.py           # Global feature flags
      terminal.py               # tmux session helpers (create, attach, send-keys)
    advance/                    # Phase gate subsystem
      orchestrator.py           # perform_advance, approve_gate, reject_gate, transition_phase
      guards.py                 # Cross-cutting AdvanceGuard classes (scope, criteria, review)
      permissions.py            # Tool permission enforcement per phase
      validators.py             # Acceptance-criteria validators
      phases/
        __init__.py             # Phase ABC, PHASE_REGISTRY, module phase loader
        preparation.py          # 0 Init, 1.0 Assessment, 1.1 Research, 1.2 Proving, 1.3 Impact, 1.4 Preparation Review gate
        planning.py             # 2.0 Planning
        execution.py            # 3.N.0 Implementation → 3.N.4 Commit (parameterized by N)
        finalization.py         # 4.0 Blind Review, 4.1 Address Fix, 4.2 Final Approval gate, 5 Done
        declarative.py          # Module-contributed phases (e.g. 2.1 Plan Review gate)
    services/                   # Domain CRUD services
      comment_service.py        # Review comments and replies
      criteria_service.py       # Acceptance criteria
      discussion_service.py     # Unified discussions (research/scope/review)
      improvement_service.py    # Global improvement tracking
      lsp_service.py            # Language-server profiles and lifecycle
      module_phase_loader.py    # Loads DeclarativePhases from modules/
      modules_discovery.py      # Discovers module directories on disk
      phase_resolver.py         # Resolves next/previous enabled phases
      phase_sequencer.py        # Builds the concrete phase sequence per workspace
      phase_settings.py         # Device + project + workspace phase toggles
      plan_service.py           # Execution plan CRUD, extend
      progress_service.py       # Progress entries per phase
      research_service.py       # Research entries with typed proofs
      rule_service.py           # Project-scoped rule files (Markdown CRUD)
      scope_service.py          # Scope map, must/may pattern resolution
      verification_service.py   # Verification profiles, step execution, result tracking
    mcp_tools/                  # MCP tool implementations (one file per domain)
      __init__.py               # Tool decorators, error envelope, workspace binding
      advance.py                # workspace_advance
      comments.py               # workspace_get_comments, post_comment, resolve_comment, submit_review_issue, get_review_issues, resolve_review_issue
      criteria.py               # workspace_propose_criteria, get_criteria, update_criteria
      improvements.py           # workspace_report_improvement, get_improvements
      plan_scope.py             # workspace_set_scope, set_plan, get_plan, extend_plan
      progress.py               # workspace_update_progress, get_progress, set_impact_analysis
      research.py               # workspace_post_discussion, save_research, list_research, get_research, prove_research, delete_research
      rules.py                  # rule_list, rule_get, rule_create, rule_update, rule_delete
      state.py                  # workspace_get_state
      verification.py           # workspace_get_verification_results, get_verification_profiles, create_verification_profile, update_verification_profile, add_verification_step, assign_verification_profile, submit_validation
    routes/                     # Flask HTTP blueprints (one per domain)
      advance.py                # Approve/reject user gates
      comments.py               # Comment + discussion CRUD, resolve, reply, hide
      context.py                # Workspace context, discussions, file references
      criteria.py               # Acceptance criteria CRUD + validation
      files.py                  # File read, directory listing, git diff
      git_config.py             # Git config management
      history.py                # Phase history rename, undo, squash
      hook_api.py               # Pre-tool hook API (check-permission, session-context)
      hooks.py                  # Session-start hook
      improvements.py           # Global improvement CRUD
      lsp.py                    # Language-server profiles + lifecycle + WebSocket
      modules.py                # Module discovery and enablement
      phase_settings.py         # Device/project/workspace phase toggles
      projects.py               # Project CRUD
      rules.py                  # Project-scoped Markdown rule files (CRUD)
      setup.py                  # Workspace setup skill launcher + WebSocket
      state.py                  # Phase, scope, plan, progress, research proving
      static.py                 # Serves templates/ (HTML, CSS, JS, i18n)
      terminal_routes.py        # Embedded terminal (tmux + xterm.js + WebSocket)
      verification.py           # Verification profiles, steps, assignment, results
      workspaces.py             # Workspace + branch management, worktree creation
    migrations/                 # Yoyo-style SQLite migrations applied on startup
    messages/                   # i18n JSON bundles (en, ru)
    tests/                      # pytest suite (27 test modules)
  templates/
    admin.html                  # Single-page admin UI
    css/                        # 21 modular stylesheets
    js/                         # 36 vanilla JS modules
    i18n/                       # Frontend translations
    img/                        # Static images
```

## Admin Panel Tabs

| Tab | Location | Purpose |
|-----|----------|---------|
| Pre-planning | Tab bar | Research summaries, impact analysis, discussions; feeds the 1.4 Preparation Review gate |
| Planning | Tab bar | Execution plan, scope contract, system and execution diagrams, acceptance criteria |
| Research | Tab bar | Full research findings with typed proof references |
| Phase Control | Tab bar | Phase progression timeline, approval status, Phase Toggles, verification results |
| Files | Sidebar | File browser with markdown preview |
| Code Changes | Sidebar | Git diff viewer |
| Configuration | Sidebar | Claude command, Git configuration, Git Rules, Rules, LSP Shortcuts, Modules, Verification Profiles, Task Context |
| Review | Sidebar | Blind code review findings and resolution workflow |
| Improvements | Sidebar | Reported process improvements with scope filtering and resolve |
| Terminal | Sidebar | Built-in terminal (tmux + xterm.js) |
| Setup | Project selector | Module selection, verification profile configuration, embedded terminal to run the setup skill |

## API Overview

All workspace endpoints are scoped under `/api/ws/<project_id>/<branch>/`.

| Group | Endpoints |
|-------|-----------|
| Projects | `GET/POST /api/projects`, `DELETE /api/projects/<id>` |
| Workspaces | `GET .../branches`, `GET/POST .../workspaces`, `PUT .../archive` |
| State | `GET .../state`, `PUT .../phase`, `PUT .../scope`, `PUT .../locale`, `PUT .../yolo`, `GET .../gate-nonce` |
| Plan/Scope Approval | `POST .../plan-status`, `POST .../scope-status` |
| Advance | `POST .../approve`, `POST .../reject` |
| Comments | `GET/POST .../comments`, `PUT .../comments/<id>/resolve`, `POST .../comments/<id>/reply` |
| Discussions | `POST .../discussions`, `PUT .../discussions/<id>/hide` |
| Context | `GET/PUT .../context`, `POST .../context/discussions`, `GET .../search-paths` |
| Research | `POST .../research/<id>/prove`, `DELETE .../research/<id>` |
| Criteria | `GET/POST .../criteria`, `PUT .../criteria/<id>`, `DELETE .../criteria/<id>`, `PUT .../criteria/<id>/validate` |
| Files | `GET .../file`, `GET .../files`, `GET .../diff` |
| Git Config | `GET/PUT .../git-config`, `GET/PUT .../git-rules` |
| Rules (project) | `GET /api/projects/<pid>/rules`, `GET /api/projects/<pid>/rules/<name>`, `POST /api/projects/<pid>/rules`, `PUT /api/projects/<pid>/rules/<name>`, `DELETE /api/projects/<pid>/rules/<name>` |
| History | `POST .../history/rename`, `POST .../history/undo`, `POST .../history/squash` |
| Hooks | `POST /api/hook/session-start` |
| Hooks API | `POST /api/hook/check-permission`, `GET /api/hook/session-context` |
| Terminal | `POST .../terminal/start`, `POST .../terminal/resume`, `GET .../terminal/status`, `POST .../terminal/kill`, `POST .../terminal/notify`, `WS /ws/terminal/<project>/<branch>` |
| Command | `GET/PUT .../command` |
| Progress | `GET /api/progress` |
| Modify Check | `POST .../can-modify` |
| Improvements | `GET /api/improvements`, `PUT /api/improvements/<id>/resolve`, `PUT /api/improvements/<id>/reopen` |
| Verification | `GET /api/verification/profiles`, `POST /api/verification/profiles`, `POST .../profiles/<id>/steps`, `PUT/DELETE /api/verification/steps/<id>`, `GET/POST .../verification/assign`, `DELETE .../verification/unassign/<id>`, `GET .../verification/results` |
| LSP | `GET .../lsp/profiles`, `GET .../lsp/status`, `POST .../lsp/start`, `POST .../lsp/stop`, `POST .../lsp/check-installed`, `PUT .../lsp/profiles/<id>/toggle`, `WS /ws/lsp/<project>/<branch>` |
| Phase Settings | `GET/PUT /api/phase-settings/device`, `GET/PUT /api/projects/<pid>/phase-settings`, `GET/PUT .../phase-settings`, `GET /api/phases/available` |
| Modules | `GET /api/modules`, `GET /api/modules/enabled`, `POST /api/modules/enabled` |
| Setup | `POST /api/setup/start`, `GET /api/setup/status`, `WS /ws/setup-terminal` |

## MCP Tools

38 tools total — 33 `workspace_*` and 5 `rule_*`.

### Plan & Scope

| Tool | Description |
|------|-------------|
| `workspace_set_scope` | Set the phase-keyed scope map (must/may file patterns) |
| `workspace_set_plan` | Set or replace the execution plan |
| `workspace_get_plan` | Get the full execution plan with all sub-phases and tasks |
| `workspace_extend_plan` | Append a new sub-phase to the plan without rewriting existing ones (auto-assigns ID, optional scope) |

### Research

| Tool | Description |
|------|-------------|
| `workspace_post_discussion` | Raise an open discussion point (research questions, decisions) |
| `workspace_save_research` | Save structured research findings with typed proofs |
| `workspace_list_research` | List all research entries (id, topic, proven status) |
| `workspace_get_research` | Get full research entries by IDs including findings |
| `workspace_prove_research` | Mark a research entry proven or rejected |
| `workspace_delete_research` | Delete a research entry |

### Comments

| Tool | Description |
|------|-------------|
| `workspace_get_comments` | Get review comments, optionally filtered by scope |
| `workspace_post_comment` | Post a review comment on a specific file and line range |
| `workspace_resolve_comment` | Mark a review comment as resolved |

### Reviews

| Tool | Description |
|------|-------------|
| `workspace_submit_review_issue` | Submit a code-review issue with severity and location |
| `workspace_get_review_issues` | Get review issues, optionally filtered by status |
| `workspace_resolve_review_issue` | Set resolution on a review issue (fixed, false_positive, out_of_scope) |

### Criteria

| Tool | Description |
|------|-------------|
| `workspace_propose_criteria` | Propose an acceptance criterion (test, scenario, or custom) |
| `workspace_get_criteria` | Get acceptance criteria, optionally filtered by status or type |
| `workspace_update_criteria` | Update an existing criterion's description or details |

### Progress & Impact

| Tool | Description |
|------|-------------|
| `workspace_update_progress` | Record progress summary for a phase |
| `workspace_get_progress` | Get progress entries, optionally filtered by phase |
| `workspace_set_impact_analysis` | Save structured impact analysis (affected flows, API changes, data flow, dependencies, ticket gaps, questions) |

### Verification

| Tool | Description |
|------|-------------|
| `workspace_get_verification_results` | Get verification run results for the current or specified phase |
| `workspace_get_verification_profiles` | List all available verification profiles |
| `workspace_create_verification_profile` | Create a new verification profile |
| `workspace_update_verification_profile` | Update an existing verification profile |
| `workspace_add_verification_step` | Add a step to a verification profile |
| `workspace_assign_verification_profile` | Assign a profile to the current workspace |
| `workspace_submit_validation` | Submit validation results from a validator sub-agent |

### Improvements

| Tool | Description |
|------|-------------|
| `workspace_report_improvement` | Report a process improvement (global — not workspace-bound) |
| `workspace_get_improvements` | Get reported improvements, optionally filtered by scope/status |

### Rules (project-scoped)

| Tool | Description |
|------|-------------|
| `rule_list` | List all rule files for the current project |
| `rule_get` | Get the full Markdown body of a named rule |
| `rule_create` | Create a new project-scoped rule file |
| `rule_update` | Update an existing rule file |
| `rule_delete` | Delete a rule file |

### State & Advance

| Tool | Description |
|------|-------------|
| `workspace_get_state` | Compact workspace state overview with summaries, counts, and `previous_sessions` |
| `workspace_advance` | Request phase advancement (backend decides the next phase; commit_hash for 3.N.4) |
