#!/usr/bin/env python3
"""PreToolUse hook: forwards every tool invocation to the admin panel API.

The admin panel is the single source of truth for permission decisions. This
hook does no local policy enforcement — it bundles the tool name, tool inputs,
and cwd into a request, asks ``/api/hook/check-permission``, and acts on the
response. Keeping every regex on the API side guarantees the rules cannot
drift between hook and server.

Fail-closed policy: when the admin API is unreachable, every tool is denied.
The whole governed workflow assumes the panel is up; an agent that finds it
down should wait for the user to start it rather than continue under guesses.
"""
import json
import os
import sys

API_BASE = os.environ.get("GOVERNED_ADMIN_API_BASE", "http://localhost:5111")

API_DOWN_DENY_REASON = (
    "Governed Workflow admin API is unavailable. Tool use is blocked until "
    "the Admin Panel is running. Start it and retry."
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


def api_check(data):
    """Call the Flask API for the permission decision.

    Returns the parsed response on success, or ``{"api_down": True}`` for any
    network/timeout/decode failure (including HTTP error responses such as
    401/500 which urllib raises as URLError subclasses).
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
    # Pass MCP tool name as command for MR-creation checks on the API side.
    request_data["command"] = tool_name

result = api_check(request_data)

if result.get("api_down"):
    deny(API_DOWN_DENY_REASON)

if not result.get("governed", False):
    allow()

if result.get("updated_command"):
    update_command(result["updated_command"])

if result.get("allowed", True):
    allow()
else:
    deny(result.get("reason", "Operation not allowed in current phase."))
