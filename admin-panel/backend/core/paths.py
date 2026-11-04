"""Central path resolution for governed-workflow.

All asset paths are resolved relative to the repository root, never to
~/.claude or any other fixed home-directory location.  This makes the
governed-workflow repo relocatable: install it anywhere and set
GOVERNED_WORKFLOW_REPO to the install path if the parents[] computation
does not match your layout.

Depth from this file to REPO_ROOT:
  admin-panel/backend/core/paths.py
  parents[0] = core/
  parents[1] = backend/
  parents[2] = admin-panel/
  parents[3] = REPO_ROOT  (contains admin-panel/, claude/, …)
"""
import os
from pathlib import Path

_repo_env = os.environ.get("GOVERNED_WORKFLOW_REPO", "")
REPO_ROOT: Path = (
    Path(_repo_env).resolve()
    if _repo_env
    else Path(__file__).resolve().parents[3]
)

DEFAULT_HOOKS_DIR = REPO_ROOT / "claude" / "hooks"
DEFAULT_AGENTS_DIR = REPO_ROOT / "claude" / "agents"
DEFAULT_RULES_DIR = REPO_ROOT / "claude" / "rules"
DEFAULT_DEFAULTS_DIR = REPO_ROOT / "claude" / "defaults"
DEFAULT_TOOLS_DIR = REPO_ROOT / "claude" / "tools"
DEFAULT_MODULES_DIR = REPO_ROOT / "claude" / "modules"
DEFAULT_MODULES_LOCAL_DIR = REPO_ROOT / "claude" / "modules-local"
DEFAULT_SKILLS_DIR = REPO_ROOT / "claude" / "skills"

DEFAULT_FUNNEL_TEMPLATE = DEFAULT_DEFAULTS_DIR / ".mcp-funnel.json"
DEFAULT_MCP_TEMPLATE = REPO_ROOT / ".mcp.json"
DEFAULT_GIT_RULES = DEFAULT_DEFAULTS_DIR / "git-rules.md"
DEFAULT_GIT_HOOKS_DIR = DEFAULT_DEFAULTS_DIR / "git-hooks"

DEFAULT_REPO_CLAUDE_MD = REPO_ROOT / "claude" / "CLAUDE.md"

STATE_DIR: Path = Path(
    os.environ.get("GOVERNED_WORKFLOW_STATE_DIR") or REPO_ROOT / ".local" / "state"
)

TELEGRAM_STATE_DIR: Path = Path(
    os.environ.get("GOVERNED_WORKFLOW_TELEGRAM_STATE")
    or REPO_ROOT / ".local" / "channels" / "telegram"
)


def hook_command(name: str, interpreter: str = "python3") -> str:
    """Return the shell command string for invoking a hook by filename.

    Args:
        name: Hook filename, e.g. ``session-start.py`` or ``user-prompt-submit.sh``.
        interpreter: Shell interpreter prefix, e.g. ``python3`` or ``bash``.

    Returns:
        A string like ``python3 /abs/path/to/repo/hooks/session-start.py``.
        Contains no ``~/.claude`` literals.
    """
    return f"{interpreter} {DEFAULT_HOOKS_DIR / name}"


def tools_dir() -> Path:
    """Return the tools directory, honoring the GOVERNED_WORKFLOW_TOOLS_DIR override.

    app.py exports GOVERNED_WORKFLOW_TOOLS_DIR at startup (defaulting to
    DEFAULT_TOOLS_DIR), so downloaded build tools and LSP launchers referenced
    from verification profile commands resolve consistently whether the
    override is set explicitly (e.g. in tests) or left to the app.py default.
    """
    return Path(os.environ.get("GOVERNED_WORKFLOW_TOOLS_DIR") or DEFAULT_TOOLS_DIR)


def admin_token_setup_command() -> str:
    """Return the absolute ``auth-token`` CLI command for the current install.

    Using an absolute path lets the user paste the command into any shell
    without needing to ``cd`` into ``admin-panel/`` first. The command is
    surfaced both as a server startup hint and in the ``/api/auth/status``
    response so the login screen can render the exact invocation.
    """
    app_py = REPO_ROOT / "admin-panel" / "backend" / "app.py"
    return f"python3 {app_py} auth-token"
