---
name: workflow-migration
description: Install or update the governed workflow + admin panel on a device
---

# Workflow Migration

Installs or updates the governed-workflow hooks, agents, rules, and admin panel so a device (and every project registered in the admin panel) can use the orchestration system.

The repository is called **governed-workflow** and can be cloned to any path on disk — `~/governed-workflow`, `/opt/governed-workflow`, etc. Examples below use `<repo>` as a placeholder for whatever path you chose.

**Platform support:** macOS (native), Linux (native), Windows (via WSL2). On Windows the entire workflow runs inside WSL2 — the browser is the only thing that runs on the Windows side.

---

## Prerequisites Check

```bash
python3 --version    # 3.10+
git --version
jq --version
sqlite3 --version
tmux -V

python3 -c "import flask; print('flask ok')" 2>&1
python3 -c "import mcp; print('mcp ok')" 2>&1
python3 -c "import flask_sock; print('flask_sock ok')" 2>&1
```

Install anything missing before continuing.

---

## Windows Setup (WSL2)

On Windows the workflow runs entirely inside WSL2. The browser accesses the admin panel via `http://localhost:5111`.

**1. Install WSL2** — PowerShell as Administrator: `wsl --install`. Ubuntu installs by default; restart when prompted.

**2. Configure Claude Code** — Windows Terminal → Settings → Startup → Default profile → Ubuntu.

**3. Install system dependencies:**
```bash
sudo apt update && sudo apt install -y python3 python3-pip git jq sqlite3 tmux curl xclip unzip zip
pip3 install flask mcp flask-sock --break-system-packages
```

**4. Clone inside the WSL filesystem** (NOT on `/mnt/c/` — too slow for git):
```bash
git clone https://github.com/IgnatRozhkoTR/governed-workflow.git ~/governed-workflow
```

**5. Configure `~/.bashrc` for non-interactive shells** — Claude Code's Bash tool runs non-interactively, so Ubuntu's default `.bashrc` exits early at the `case $-` guard. Put all exports **before** that guard:
```bash
export JAVA_HOME="/home/$USER/.sdkman/candidates/java/current"
export PATH="$JAVA_HOME/bin:$HOME/.local/bin:$PATH"
export ANTHROPIC_BASE_URL=https://your-proxy-if-any
```

**6. Install JDKs via SDKMAN** (optional, only if you work on JVM projects):
```bash
curl -s "https://get.sdkman.io" | bash
source ~/.sdkman/bin/sdkman-init.sh
sdk install java 21.0.7-tem && sdk default java 21.0.7-tem
```
Corporate SSL issues: create a `-k` curl wrapper in `~/.local/bin/curl`, remove after install.

**7. Git credentials** — prefer HTTPS for corporate GitHub orgs:
```bash
gh auth login && gh auth setup-git
```
Install `gh` CLI as a binary if needed (download from GitHub releases into `~/.local/bin/`).

**8. tmux config:**
```bash
cat > ~/.tmux.conf << 'EOF'
set -g mouse on
set -g history-limit 10000
bind -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "xclip -selection clipboard"
EOF
```

After WSL setup, continue with the install steps below — they work identically inside WSL.

---

## Install Steps

### 1. Clone the repo

```bash
git clone https://github.com/IgnatRozhkoTR/governed-workflow.git ~/governed-workflow   # or any path you prefer
cd ~/governed-workflow
```

### 2. (Optional) Export repo path

`core/paths.py` auto-detects the repo root when launched from `admin-panel/server/*`, so this is mostly a safety override for shells launched outside the repo:
```bash
echo 'export GOVERNED_WORKFLOW_REPO=~/governed-workflow' >> ~/.bashrc
```

### 3. Install Python dependencies

```bash
cd <repo>/admin-panel
python3 -m venv .venv
source .venv/bin/activate
pip install flask mcp flask-sock
```
Or without a venv: `pip3 install flask mcp flask-sock [--break-system-packages]`

### 4. Verify the repo's own `.claude/settings.json`

The repo ships with its own `.claude/settings.json` used whenever Claude Code is opened on the repo itself. Hook commands use `${CLAUDE_PROJECT_DIR}` so they resolve regardless of where the repo is cloned. Confirm:

```bash
grep CLAUDE_PROJECT_DIR <repo>/.claude/settings.json
```

You should see paths like `${CLAUDE_PROJECT_DIR}/claude/hooks/pre-tool-hook.py`. If the file is missing or has been corrupted, restore it from git:

```bash
cd <repo> && git checkout HEAD -- .claude/settings.json
```

### 5. Initialize the database

The server auto-applies migrations from `admin-panel/server/migrations/` on first start. If you prefer to initialize explicitly:

```bash
cd <repo>/admin-panel/server
python3 -c "from core.db import init_db; init_db(); print('DB initialized')"
```

### 6. Global hooks must NOT be configured

Hooks live at the **project level** (`<project>/.claude/settings.json`), not globally. Make sure `~/.claude/settings.json` has no `hooks` or `statusLine` entries that would leak into every session:

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".claude/settings.json"
if not p.exists():
    print("OK — no global settings file")
    raise SystemExit
d = json.loads(p.read_text())
changed = False
for key in ("hooks", "statusLine"):
    if key in d:
        d.pop(key)
        changed = True
if changed:
    p.write_text(json.dumps(d, indent=2))
    print("Removed stale global entries; restart Claude Code sessions.")
else:
    print("OK — no stale global entries")
PY
```

### 7. Configure MCP server in each project

For every project that uses the governed workflow, create `.mcp.json` in the project root. Use the absolute expanded path — no `~` or `$HOME`:
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
Add `.mcp.json` to your global gitignore so it never ends up in a project repo:
```bash
echo '.mcp.json' >> ~/.gitignore_global
git config --global core.excludesfile ~/.gitignore_global
```

### 8. Start the admin panel

Use tmux so the server survives terminal closes:
```bash
tmux new-session -d -s admin-panel "cd <repo>/admin-panel/server && python3 app.py"
```

Convenience shell function (add before the interactive guard in `~/.bashrc`):
```bash
REPO=~/governed-workflow   # adjust to your path
ccadmin() {
  pkill -f "admin-panel/server/app.py" 2>/dev/null; sleep 1
  tmux kill-session -t admin-panel 2>/dev/null || true
  tmux new-session -d -s admin-panel "cd $REPO/admin-panel/server && python3 app.py"
  for i in 1 2 3 4 5; do
    sleep 1
    pgrep -f "admin-panel/server/app.py" > /dev/null && echo "Admin panel started on port 5111" && return
  done
  echo "Failed — check: tmux attach -t admin-panel"
}
```

### 9. Configure a project in the admin panel

Open `http://localhost:5111` and create a project pointing to your project directory.

### 10. Create a workspace

From the admin panel, create a workspace (branch). The server automatically merges the defaults from `<repo>/claude/defaults/` and `<repo>/codex/` with any project-local `.claude/` and `.codex/` overrides, then writes the merged result into the workspace's `.claude/` and `.codex/` directories.

Verify:
```bash
ls <your-project>/.claude/workspaces/<branch>/
# Should contain merged settings, rules, agents, etc.
```

---

## Updating an Existing Install

To pick up changes after a `git pull` on the repo:

1. Restart the admin panel so it reloads Python code, migrations, and module registrations:
   ```bash
   tmux kill-session -t admin-panel 2>/dev/null || true
   tmux new-session -d -s admin-panel "cd <repo>/admin-panel/server && python3 app.py"
   ```
2. Restart any open Claude Code sessions — hooks are snapshotted at session start, so running sessions keep using the old versions until restarted.
3. Newly-created workspaces automatically receive the latest agents, rules, defaults, and codex assets. Existing workspaces keep their current content — delete a file under `<project>/.claude/workspaces/<branch>/` if you want the next create/re-create to pick up the repo version.

No database migration is needed beyond what the admin panel runs automatically on startup.

---

## Verify Hooks Work

```bash
echo '{"tool_name":"Write","tool_input":{},"cwd":"/tmp"}' \
  | python3 <repo>/claude/hooks/block-orchestrator-writes.py
echo "exit: $?"  # Should be 0

echo '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/test.txt"},"cwd":"/tmp"}' \
  | python3 <repo>/claude/hooks/pre-tool-hook.py
echo "exit: $?"  # Should be 0
```

---

## Component Inventory

| Component | Path | Purpose |
|-----------|------|---------|
| Admin panel server | `<repo>/admin-panel/server/` | Flask app (port 5111) + SQLite DB |
| MCP server | `<repo>/admin-panel/server/mcp_server.py` | 38 workspace tools via stdio |
| Orchestrator block hook | `<repo>/claude/hooks/block-orchestrator-writes.py` | Prevents the main agent from writing files in git repos |
| Phase gate hook | `<repo>/claude/hooks/pre-tool-hook.py` | Enforces edit/commit/push restrictions per phase |
| Session start hook | `<repo>/claude/hooks/session-start.py` | Registers sessions, outputs recovery context |
| Agent definitions | `<repo>/claude/agents/` | 16 agent types (researchers, engineers, validators, reviewers) |
| Rules | `<repo>/claude/rules/*.md` | Coding standards, test standards, validation pipeline (YAML-frontmatter auto-load) |
| Workflow skill | `<repo>/claude/skills/governed-workflow/SKILL.md` | Phase map, rules, MCP tool reference |
| Plan-preparation skill | `<repo>/claude/skills/plan-preparation/SKILL.md` | Guides phases 1.0-1.4 |
| Planning skill | `<repo>/claude/skills/planning/SKILL.md` | Guides phase 2.0 |
| Setup skill | `<repo>/claude/skills/setup/SKILL.md` | Runs the admin-panel setup wizard |
| Rules skill | `<repo>/claude/skills/rules/SKILL.md` | Author/edit rule files via MCP |
| Default git rules | `<repo>/claude/defaults/git-rules.md` | Commit/MR format rules |
| Modules | `<repo>/claude/modules/` | Self-contained feature packages (telegram, ...) |
| Migration skill | `<repo>/.claude/skills/workflow-migration/` | This skill — repo-only, not shipped to workspaces |

---

## Admin Panel Tabs

| Tab | Location | Purpose |
|-----|----------|---------|
| Pre-planning | Tab bar | Research summaries, impact analysis, discussions, phase 1.4 gate |
| Planning | Tab bar | Execution plan, scope, system diagrams, acceptance criteria |
| Research | Tab bar | Full research findings with proof references |
| Phase Control | Tab bar | Phase progression, approval status, per-workspace phase toggles |
| Files | Sidebar | File browser |
| Code Changes | Sidebar | Git diff viewer |
| Configuration | Sidebar | Workspace settings, Claude command |
| Settings | Sidebar | Git Rules card, Rules card, other device/project settings |
| Review | Sidebar | Code review issues |
| Improvements | Sidebar | Reported process improvements |
| Terminal | Sidebar | Built-in terminal (tmux-based) |
| Setup | Project selector | Module and verification-profile wizard |

---

## Dependencies

- **tmux**: `apt install tmux` (Linux/WSL) or `brew install tmux` (macOS)
- **xclip** (WSL only): `apt install xclip` — clipboard between WSL tmux and Windows
- **flask-sock**: `pip3 install flask-sock [--break-system-packages]` — WebSocket terminal support
- **gh CLI**: for HTTPS git credential helper

---

## Optional: Telegram Integration

For remote session control via Telegram:

1. Create a bot via [@BotFather](https://t.me/BotFather) and get the token
2. Install Bun runtime: `curl -fsSL https://bun.sh/install | bash`
3. Install the Claude Code Telegram plugin: `/plugin install telegram@claude-plugins-official`
4. Configure the token: `/telegram:configure <token>`
5. Enable the module via the admin panel Setup page, or run the `telegram` module's `enable` dispatch through the setup skill
6. Enable channels in the admin panel: Configuration → Device Settings → toggle Channels on

---

## Troubleshooting

- **MCP server not connecting**: Check `.mcp.json` path is absolute and the file exists. Restart Claude Code after adding `.mcp.json`.
- **Hook not firing**: Hooks are snapshotted at session start. Restart the session after changing `settings.json`.
- **DB errors**: Stop the admin panel, delete `<repo>/admin-panel/server/admin-panel.db*` files, and restart — migrations will recreate the schema.
- **Flask server not starting**: Check port 5111 is free (`lsof -i :5111`).
- **`java`/`mvn` not found**: Exports are after the `.bashrc` interactive guard — move them above `# If not running interactively`.
- **pip3 install fails**: Add `--break-system-packages` on Ubuntu 24.04+.
- **SSH git push/fetch blocked**: Switch to HTTPS + `gh auth setup-git`.
- **`localhost:5111` not accessible on Windows**: Run `ip addr show eth0` in WSL to find its IP.
- **Slow git on Windows**: Ensure the project is in the WSL filesystem (`~/`), not `/mnt/c/`.
