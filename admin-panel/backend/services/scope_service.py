"""Scope domain logic: set scope into the plan and pattern matching for workspace scope.

Scope lives inside each plan execution item under a "scope" key. This module is
the single adapter: callers set scope as a phase-keyed map and read patterns
through the accessors here, which operate on the reconstructed map. MCP tools and
route handlers are thin wrappers that delegate to this module.
"""
import json
import re

from core.helpers import match_scope_pattern
from core.i18n import t
from core.phase import phase_key
from services import plan_service

_PHASE_3_SUB_RE = re.compile(r'^3\.\d+\.\d+$')


def set_scope(db, ws, scope_data, enforce_phase_guard=True):
    """Merge a phase-keyed scope map into the plan's execution items and revoke approval.

    Scope is part of the plan now: each entry of ``scope_data`` (keyed by a
    "3.N" sub-phase id) is written onto the matching execution item's "scope"
    key. When enforce_phase_guard=True (default, used by MCP), rejects updates
    at phase 0; when False (admin UI), allows updates at any phase. Editing
    scope resets plan_status so the user must re-approve.
    Returns a result dict with ok/error keys.
    """
    locale = ws["locale"] or "en"
    phase = ws["phase"]

    if enforce_phase_guard and phase_key(phase) < phase_key("1.0"):
        return {"error": t("mcp.error.scopePhase0", locale)}

    plan = plan_service.get_plan(ws)
    for item in plan.get("execution", []):
        entry = scope_data.get(item.get("id"))
        if isinstance(entry, dict):
            item["scope"] = entry

    db.execute("UPDATE workspaces SET plan_json = ? WHERE id = ?", (json.dumps(plan), ws["id"]))
    db.execute("UPDATE workspaces SET plan_status = 'pending' WHERE id = ?", (ws["id"],))

    return {"ok": True, "phase": phase, "plan_status": "pending",
            "note": t("mcp.error.scopeNoteRevoked", locale)}


def get_scope_patterns(scope, phase):
    """Return (must_patterns, may_patterns) for the given phase from a parsed scope map.

    For 3.N.K phases: uses the 3.N sub-key only.
    For all other phases: aggregates across all phase entries in the scope map.

    Args:
        scope: parsed scope dict (phase-keyed map reconstructed from the plan)
        phase: current phase string e.g. "3.1.0", "2.0"

    Returns:
        tuple of (must_patterns list, may_patterns list)
    """
    if _PHASE_3_SUB_RE.match(phase):
        parts = phase.split(".")
        sub_key = parts[0] + "." + parts[1]
        phase_scope = scope.get(sub_key, {})
        return phase_scope.get("must", []), phase_scope.get("may", [])

    must_patterns = []
    may_patterns = []
    for ps in scope.values():
        if isinstance(ps, dict):
            must_patterns.extend(ps.get("must", []))
            may_patterns.extend(ps.get("may", []))
    return must_patterns, may_patterns


def get_phase_must_patterns(scope, phase):
    """Return only 'must' patterns for the current sub-phase.

    Always scopes to the specific 3.N sub-key, never aggregates.
    Used by advance validation which needs per-sub-phase must coverage.

    Args:
        scope: parsed scope dict
        phase: current phase string e.g. "3.1.0"

    Returns:
        list of must pattern strings
    """
    parts = phase.split(".")
    sub_key = parts[0] + "." + parts[1] if len(parts) >= 2 else phase
    phase_scope = scope.get(sub_key, {})
    return phase_scope.get("must", [])


def match_scope_patterns(file_path, scope, phase):
    """Check if a relative file path matches any must or may scope pattern for the phase.

    Args:
        file_path: relative file path (e.g. "src/main.py")
        scope: parsed scope dict (phase-keyed map)
        phase: current phase string

    Returns:
        True if the file matches at least one pattern, False otherwise.
    """
    must_patterns, may_patterns = get_scope_patterns(scope, phase)
    all_patterns = must_patterns + may_patterns

    if not all_patterns:
        return True

    for pattern in all_patterns:
        match_pattern = pattern.rstrip("/") + "/**" if pattern.endswith("/") else pattern
        if match_scope_pattern(file_path, match_pattern):
            return True
    return False
