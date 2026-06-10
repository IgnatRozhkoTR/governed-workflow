# Workspace Control

The admin panel and MCP server for the [governed workflow](../README.md). Flask web application that manages workspaces, enforces phase transitions, and provides the MCP tools agents interact with. See the root README for the workflow overview and diagram.

## Architecture

| Layer | Details |
|-------|---------|
| Backend | Flask with Blueprints |
| Frontend | Vanilla HTML/CSS/JS |
| Storage | SQLite (`backend/admin-panel.db`) |
| Agent Interface | MCP server over stdio (`backend/mcp_server.py`) |
| i18n | JSON message bundles (`backend/messages/`) |
| Tests | pytest suite (`backend/tests/`) |

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
cd <repo>/admin-panel/backend
python3 app.py
```

The server starts at http://localhost:5111. The SQLite database is created automatically on first run.

### Admin token

Auth is always on. Generate a token from a shell on the host:

```bash
python3 backend/app.py auth-token
```

The CLI prints the token and copies it to the system clipboard. Paste it into the admin panel login screen — the token persists in browser localStorage. Re-running with `--force` rotates the token (and disconnects any open sessions). To clear:

```bash
python3 backend/app.py auth-reset
```

Only the SHA-256 hash is stored on disk (in the `device_settings` table); the plaintext is never persisted. There is no environment variable that disables the middleware. See the root [Security Model](../README.md#security-model) for the full set of trust boundaries.

### Network mode

By default the panel binds `127.0.0.1:5111` (localhost only). The Configuration page has a Network Mode toggle that switches the bind host to `0.0.0.0:5111` so the panel is reachable from another device on the LAN. The admin token is still required. Restart is triggered automatically. Never enable on an untrusted network.

### MCP Server

Add to your `.mcp.json` (use absolute expanded paths — no `~` or `$HOME`):

```json
{
  "mcpServers": {
    "governed-workflow": {
      "command": "/absolute/path/to/governed-workflow/admin-panel/.venv/bin/python3",
      "args": ["-m", "mcp_server"],
      "cwd": "/absolute/path/to/governed-workflow/admin-panel/backend"
    }
  }
}
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
| Terminal | Sidebar | Built-in terminal (tmux + xterm.js) |
| Setup | Project selector | Module selection, verification profile configuration, embedded terminal to run the setup skill |

## API Overview

All workspace endpoints are scoped under `/api/ws/<project_id>/<branch>/`.

| Group | Endpoints |
|-------|-----------|
| Projects | `GET/POST /api/projects`, `DELETE /api/projects/<id>` |
| Workspaces | `GET .../branches`, `GET/POST .../workspaces`, `PUT .../archive` |
| Auth | `GET /api/auth/status`, `POST /api/auth/check` |
| State | `GET .../state`, `PUT .../phase`, `PUT .../scope`, `PUT .../locale`, `PUT .../yolo` |
| Network | `GET/PUT /api/network-mode`, `POST /api/restart` |
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
| Verification | `GET /api/verification/profiles`, `POST /api/verification/profiles`, `POST .../profiles/<id>/steps`, `PUT/DELETE /api/verification/steps/<id>`, `GET/POST .../verification/assign`, `DELETE .../verification/unassign/<id>`, `GET .../verification/results` |
| LSP | `GET .../lsp/profiles`, `GET .../lsp/status`, `POST .../lsp/start`, `POST .../lsp/stop`, `POST .../lsp/check-installed`, `PUT .../lsp/profiles/<id>/toggle`, `WS /ws/lsp/<project>/<branch>` |
| Phase Settings | `GET/PUT /api/phase-settings/device`, `GET/PUT /api/projects/<pid>/phase-settings`, `GET/PUT .../phase-settings`, `GET /api/phases/available` |
| Modules | `GET /api/modules`, `GET /api/modules/enabled`, `POST /api/modules/enabled` |
| Setup | `POST /api/setup/start`, `GET /api/setup/status`, `WS /ws/setup-terminal` |

## MCP Tools

40 tools total — 35 `workspace_*` and 5 `rule_*`.

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

### Rules (project-scoped)

| Tool | Description |
|------|-------------|
| `rule_list` | List all rule files for the current project |
| `rule_get` | Get the full Markdown body of a named rule |
| `rule_create` | Create a new project-scoped rule file |
| `rule_update` | Update an existing rule file |
| `rule_delete` | Delete a rule file |

### Reflection

| Tool | Description | Gated to |
|------|-------------|----------|
| `workspace_get_reflection_context` | Returns scope, branch diff, open review findings, and filtered session transcript for the reflector | `orchestrator` |
| `workspace_submit_proposal` | Submit a reflection proposal (nine types: memory/rule/agent/skill writes, workflow improvement; `auto` or `manual` implementation) | `reflector` |
| `workspace_list_proposals` | List all proposals with status | `orchestrator` |
| `workspace_resolve_proposal` | Mark a proposal `executed`, `failed`, or `rejected` | `orchestrator` |

### Review pipeline

| Tool | Description | Gated to |
|------|-------------|----------|
| `workspace_review_pipeline_summary` | Returns pipeline completion/success state so the orchestrator can gate `workspace_advance` at 4.0 | `orchestrator` |

### State & Advance

| Tool | Description |
|------|-------------|
| `workspace_get_state` | Compact workspace state overview with summaries, counts, and `previous_sessions_count` |
| `workspace_advance` | Request phase advancement (backend decides the next phase; commit_hash for 3.N.4) |
