#!/usr/bin/env python3
"""PreToolUse hook: enforces phase gates, scope restrictions, and security boundaries.

Calls the Flask admin panel API for workspace/phase/scope decisions.
Handles security checks (bypass prevention) locally — no API needed.

Fail-closed policy (when the admin API is unreachable):
    - Clearly read-only tools (Read, Grep, Glob, LS, NotebookRead, WebFetch,
      WebSearch, TodoRead, and MCP tools whose names contain get/list/read/
      search/status) are allowed with a comment that the API is unreachable.
    - Clearly write-blocking tools (Edit, Write, MultiEdit, NotebookEdit) are
      denied.
    - Bash is denied when the command matches the file-modifying pattern,
      recording/destructive git commands, or direct calls to the admin API;
      otherwise Bash is allowed with a comment.
    - MCP tools whose names suggest approval/auth/admin behavior are denied
      even on API failure (approve, reject, auth, admin, gate_nonce).

The existing hardcoded security checks (curl/wget to admin, direct sqlite3
access, curl to approve/reject endpoints) run before any API call and deny
regardless of API state.
"""
import json
import sys
import re
import os
from pathlib import Path
from _repo_root import GOVERNED_REPO_ROOT, ADMIN_PANEL_DIR

API_BASE = os.environ.get("GOVERNED_ADMIN_API_BASE", "http://localhost:5111")

API_DOWN_DENY_REASON = (
    "Governed Workflow admin API is unavailable. "
    "Write operations are blocked until the Admin Panel is running. "
    "Start the panel and retry."
)

READ_ONLY_TOOLS = frozenset({
    "Read", "Grep", "Glob", "LS", "NotebookRead",
    "WebFetch", "WebSearch", "TodoRead",
})

WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

READ_ONLY_MCP_KEYWORDS = ("get", "list", "read", "search", "status")
SENSITIVE_MCP_KEYWORDS = ("approve", "reject", "auth", "admin", "gate_nonce")

FILE_MOD_PATTERN = re.compile(
    r'(?<!\d\s)>\s|>>\s|\btee\s|\bdd\s.*\bof=|sed\s+-i|perl\s+-i'
    r'|python3?\s.*open\(|python3?\s.*write_text|python3?\s.*write_bytes|python3?\s.*Path\('
    r'|python3?\s*<<|echo\s.*\|\s*python3?'
    r'|ruby\s+-e.*File'
    r'|\bcp\s|\bmv\s|\brm\s|\brmdir\s|\bln\s'
    r'|\bchmod\s|\bchown\s|\btruncate\s|\bpatch\s'
    r'|\bfind\s.*-delete|\bfind\s.*-exec\s+rm'
    r'|install\s+-'
)

GIT_BLOCK_PATTERN = re.compile(
    r'\bgit\s+(?:'
    r'add\b'
    r'|commit\b'
    r'|push\b'
    r'|checkout\s+--'
    r'|restore\b'
    r'|clean\b'
    r'|reset\s+--hard\b'
    r'|rebase\b'
    r'|merge\b'
    r'|branch\s+-D\b'
    r'|worktree\s+remove\b'
    r'|tag\s+-d\b'
    r')'
)

ADMIN_API_CALL_PATTERN = re.compile(
    r'\b(?:curl|wget|http|fetch)\b[^|&;]*?(?:localhost|127\.0\.0\.1):5111'
)


def deny(reason):
    full_reason = reason + " Do NOT bypass hooks — ask the user to adjust scope or phase via the admin panel."
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": full_reason
        }
    }, sys.stdout)
    sys.exit(0)


def update_command(new_command):
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {"command": new_command}
        }
    }, sys.stdout)
    sys.exit(0)


def allow():
    sys.exit(0)


def allow_with_comment(comment):
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": comment,
        }
    }, sys.stdout)
    sys.exit(0)


def _mcp_name_matches(tool_name, keywords):
    lowered = tool_name.lower()
    return any(keyword in lowered for keyword in keywords)


def _is_read_only_tool(tool_name):
    if tool_name in READ_ONLY_TOOLS:
        return True
    if tool_name.startswith("mcp") and _mcp_name_matches(tool_name, READ_ONLY_MCP_KEYWORDS):
        return True
    return False


def _allow_when_api_down(tool_name, tool_input):
    """Fail-closed classifier used when the admin API is unreachable.

    Returns (allowed, message). The message is emitted to the agent in either
    branch so the cause is visible in the transcript.
    """
    if tool_name.startswith("mcp") and _mcp_name_matches(tool_name, SENSITIVE_MCP_KEYWORDS):
        return False, API_DOWN_DENY_REASON

    if _is_read_only_tool(tool_name):
        return True, "Admin API unreachable — read-only tool allowed."

    if tool_name in WRITE_TOOLS:
        return False, API_DOWN_DENY_REASON

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if ADMIN_API_CALL_PATTERN.search(command):
            return False, API_DOWN_DENY_REASON
        if FILE_MOD_PATTERN.search(command):
            return False, API_DOWN_DENY_REASON
        if GIT_BLOCK_PATTERN.search(command):
            return False, API_DOWN_DENY_REASON
        return True, "Admin API unreachable — non-modifying Bash command allowed."

    return True, "Admin API unreachable — tool not classified as write, allowed."


def api_check(data):
    """Call the Flask API for permission check.

    Returns one of:
        {"governed": True/False, "allowed": bool, "reason": str, ...}  — API responded
        {"api_down": True}                                              — API unreachable
    """
    import urllib.request
    import urllib.error

    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        API_BASE + "/api/hook/check-permission",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {"api_down": True}


# ─── MAIN ───

data = json.load(sys.stdin)
tool_name = data.get("tool_name", "")
tool_input = data.get("tool_input", {})
cwd = data.get("cwd", ".")

_GOVERNED_WORKFLOW_ROOT_STR = str(GOVERNED_REPO_ROOT)


def _cwd_is_inside_governed_workflow(current_dir):
    """True when the agent's cwd lives under the governed-workflow install tree.

    Used as a local fail-closed proxy for "is the current workspace the
    governed-workflow repo itself?". Without this escape hatch a maintainer
    working on the admin-panel source would be locked out of their own tree.
    """
    try:
        resolved = Path(current_dir).resolve()
    except (OSError, ValueError):
        return False
    root = Path(_GOVERNED_WORKFLOW_ROOT_STR)
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
        return False


def _path_is_inside_governed_workflow(abs_path):
    if not abs_path:
        return False
    try:
        resolved = Path(abs_path).resolve()
    except (OSError, ValueError):
        resolved = Path(os.path.normpath(abs_path))
    root = Path(_GOVERNED_WORKFLOW_ROOT_STR)
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
        return False


GOVERNED_WORKFLOW_DENIAL_REASON = (
    "Modifications to the governed-workflow installation are blocked from user "
    "workspaces. Edit governed-workflow source only from a workspace rooted in "
    "the governed-workflow repo itself."
)

# ─── LOCAL SECURITY CHECKS (must stay in hook, not API) ───

if tool_name == "Bash":
    command = tool_input.get("command", "")

    # Block curl/wget to admin panel
    if re.search(r'(curl|wget|http|fetch).*localhost:5111', command):
        deny("Direct HTTP requests to admin panel are blocked. Use MCP workspace tools.")

    # Block direct DB access
    if re.search(r'sqlite3.*admin-panel', command) or 'gate_nonce' in command:
        deny("Direct database access is blocked.")

    # Block any reference to the admin-panel SQLite DB even via cat/python/etc.
    if re.search(r'admin-panel\.db', command):
        deny("Direct access to the admin-panel database file is blocked.")

    # Block curl to approve/reject endpoints
    if re.search(r'curl.*(approve|reject)', command):
        deny("Direct API calls to approve/reject are blocked. Use the admin panel UI.")

    # Block any bash command referencing paths inside the governed-workflow
    # installation — unless the current workspace is the governed-workflow
    # repo itself (self-edit exception for maintainers).
    if _GOVERNED_WORKFLOW_ROOT_STR in command and not _cwd_is_inside_governed_workflow(cwd):
        deny(GOVERNED_WORKFLOW_DENIAL_REASON)

if tool_name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
    file_path_for_block = tool_input.get("file_path", "")
    if file_path_for_block and not os.path.isabs(file_path_for_block):
        file_path_for_block = os.path.join(cwd, file_path_for_block)
    if file_path_for_block and _path_is_inside_governed_workflow(file_path_for_block) \
            and not _cwd_is_inside_governed_workflow(cwd):
        deny(GOVERNED_WORKFLOW_DENIAL_REASON)

# ─── ALLOW ORCHESTRATOR METADATA WRITES ───

if tool_name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
    file_path = tool_input.get("file_path", "")
    resolved_fp = Path(os.path.normpath(os.path.join(cwd, file_path))) if file_path else Path()
    is_claude_metadata = "/.claude/" in file_path
    is_worktrees_path = "/.claude/worktrees/" in file_path
    is_admin_panel_path = resolved_fp.is_relative_to(ADMIN_PANEL_DIR)
    if is_claude_metadata and not is_worktrees_path and not is_admin_panel_path:
        allow()

# ─── ALLOW DOCKER COMMANDS ───

if tool_name == "Bash":
    command = tool_input.get("command", "")
    if re.match(r'\s*(docker|docker-compose|podman)\s', command):
        allow()

# ─── API CHECK FOR WORKSPACE/PHASE/SCOPE ───

request_data = {
    "cwd": cwd,
    "tool_name": tool_name,
}

if tool_name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
    file_path = tool_input.get("file_path", "")
    if file_path and not os.path.isabs(file_path):
        file_path = os.path.join(cwd, file_path)
    request_data["file_path"] = os.path.normpath(file_path) if file_path else ""

if tool_name == "Bash":
    request_data["command"] = tool_input.get("command", "")

if tool_name and tool_name.startswith("mcp"):
    request_data["command"] = tool_name  # Pass MCP tool name as command for MR checks

result = api_check(request_data)

if result.get("api_down"):
    allowed, message = _allow_when_api_down(tool_name, tool_input)
    if allowed:
        allow_with_comment(message)
    else:
        deny(message)

if not result.get("governed", False):
    allow()

if result.get("updated_command"):
    update_command(result["updated_command"])

if result.get("allowed", True):
    allow()
else:
    deny(result.get("reason", "Operation not allowed in current phase."))
