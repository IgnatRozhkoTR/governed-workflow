"""Workspace state routes: phase, scope, plan, progress."""
import hashlib
import json
import logging
import re
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger(__name__)

from core.db import ws_field
from services import comment_service
from services import discussion_service
from core.decorators import with_workspace
from core.i18n import t
from core.terminal import notify_workspace
from services import plan_service
from services import progress_service
from services import research_service
from services import scope_service
from services.phase_sequencer import resolve_phase_sequence

def _group_comments(comments):
    """Group a flat list of comment dicts by 'scope:target' key."""
    grouped = {}
    for comment in comments:
        key = f"{comment['scope']}:{comment['target'] or ''}"
        grouped.setdefault(key, []).append(comment)
    return grouped


# Phases that have sub-phases — bare number normalizes to .0
_PHASES_WITH_SUBS = {"1", "2", "3", "4"}

# Static phase ids that are always valid without consulting the registry.
_STATIC_PHASE_RE = re.compile(
    r'^(0|1\.[0-4]|2\.0|3\.\d+\.[0-4]|4\.[0-2]|5\.[12]|6)$'
)


def normalize_phase(phase):
    """Normalize and validate a phase string. Returns the normalized phase or None.

    Static workflow phases match the legacy regex. Module-contributed phases
    (with non-numeric ids) are accepted when registered in PHASE_REGISTRY so
    ``set_phase`` can move a workspace into a module phase by id.
    """
    phase = phase.strip()
    if phase in _PHASES_WITH_SUBS:
        phase = phase + ".0"
    if _STATIC_PHASE_RE.match(phase):
        return phase
    from advance.phases import PHASE_REGISTRY
    if phase in PHASE_REGISTRY:
        return phase
    return None

bp = Blueprint("state", __name__)


@bp.route("/api/ws/<project_id>/<path:branch>/state", methods=["GET"])
@with_workspace
def get_workspace_state(db, ws, project):
    comments = _group_comments(comment_service.get_comments(db, ws["id"]))

    scope = plan_service.get_scope(ws)
    plan = plan_service.get_plan(ws)
    _, phase_sequence = resolve_phase_sequence(db, ws, plan)

    history_rows = db.execute(
        "SELECT from_phase, to_phase, time FROM phase_history WHERE workspace_id = ? ORDER BY id",
        (ws["id"],)
    ).fetchall()
    history = [{"from": row["from_phase"], "to": row["to_phase"], "time": row["time"]} for row in history_rows]

    session_rows = db.execute(
        "SELECT session_id, started_at FROM session_history "
        "WHERE workspace_id = ? ORDER BY id DESC",
        (ws["id"],)
    ).fetchall()
    sessions = [{"session_id": r["session_id"], "started_at": r["started_at"]} for r in session_rows]

    all_ids = [e["id"] for e in research_service.list_research(db, ws["id"])]
    research = research_service.get_research(db, ws["id"], all_ids)

    discussions = discussion_service.list_discussions(db, ws["id"])

    progress = progress_service.get_progress(db, ws["id"])

    impact_analysis = None
    if "impact_analysis_json" in ws.keys() and ws["impact_analysis_json"]:
        try:
            impact_analysis = json.loads(ws["impact_analysis_json"])
        except json.JSONDecodeError:
            pass

    payload = {
        "workspace_id": ws["id"],
        "phase": ws["phase"],
        "status": ws["status"],
        "scope": scope,
        "scope_status": ws["scope_status"],
        "plan": plan,
        "plan_status": ws["plan_status"],
        "phase_sequence": phase_sequence,
        "locale": ws["locale"],
        "session_id": ws["session_id"],
        "working_dir": ws["working_dir"],
        "branch": ws["branch"],
        "claude_command": ws["claude_command"] or "claude",
        "skip_permissions": bool(ws["skip_permissions"]),
        "restrict_to_workspace": bool(ws_field(ws, "restrict_to_workspace", 1)),
        "allowed_external_paths": ws_field(ws, "allowed_external_paths", "/tmp/"),
        "comments": comments,
        "research": research,
        "discussions": discussions,
        "phaseHistory": history,
        "progress": progress,
        "sessions": sessions,
        "impact_analysis": impact_analysis,
        "yolo_mode": bool(ws_field(ws, "yolo_mode", 0)),
    }

    body_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    etag = hashlib.md5(body_bytes).hexdigest()

    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

    return Response(
        body_bytes,
        status=200,
        mimetype="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@bp.route("/api/ws/<project_id>/<path:branch>/locale", methods=["PUT"])
@with_workspace
def set_locale(db, ws, project):
    body = request.get_json(silent=True) or {}
    locale = body.get("locale", "en").strip()
    if locale not in ("en", "ru"):
        return jsonify({"error": t("api.error.unsupportedLocale")}), 400
    db.execute("UPDATE workspaces SET locale = ? WHERE id = ?", (locale, ws["id"]))
    db.commit()
    return jsonify({"ok": True, "locale": locale})


@bp.route("/api/ws/<project_id>/<path:branch>/yolo", methods=["PUT"])
@with_workspace
def set_yolo_mode(db, ws, project):
    body = request.get_json(silent=True) or {}
    enabled = 1 if body.get("enabled") else 0
    db.execute("UPDATE workspaces SET yolo_mode = ? WHERE id = ?", (enabled, ws["id"]))
    db.commit()
    return jsonify({"ok": True, "yolo_mode": bool(enabled)})


@bp.route("/api/ws/<project_id>/<path:branch>/scope", methods=["PUT"])
@with_workspace
def set_scope(db, ws, project):
    """Update workspace scope as a phase-keyed map."""
    body = request.get_json(silent=True) or {}
    scope = body.get("scope", {})

    result = scope_service.set_scope(db, ws, scope, enforce_phase_guard=False)
    if "error" in result:
        return jsonify(result), 400
    db.commit()
    return jsonify({"ok": True, "scope": scope})


@bp.route("/api/ws/<project_id>/<path:branch>/scope-status", methods=["POST"])
@with_workspace
def set_scope_status(db, ws, project):
    """Set scope status: pending, approved, or rejected."""
    body = request.get_json(silent=True) or {}
    status = body.get("status", "pending")
    result = scope_service.set_scope_status(db, ws["id"], status, locale=ws["locale"])
    if "error" in result:
        return jsonify(result), 400
    db.commit()

    if status == 'approved':
        notify_workspace(ws, 'Scope has been approved.')
    elif status == 'rejected':
        notify_workspace(ws, 'Scope has been rejected. Check comments for feedback.')

    return jsonify({"ok": True, "scope_status": status})


@bp.route("/api/ws/<project_id>/<path:branch>/plan-status", methods=["POST"])
@with_workspace
def set_plan_status(db, ws, project):
    """Set plan status: pending, approved, or rejected."""
    body = request.get_json(silent=True) or {}
    status = body.get("status", "pending")
    if status not in ("pending", "approved", "rejected"):
        return jsonify({"error": t("api.error.invalidStatus")}), 400
    db.execute("UPDATE workspaces SET plan_status = ? WHERE id = ?", (status, ws["id"]))
    db.commit()

    if status == 'approved':
        notify_workspace(ws, 'Plan has been approved.')
    elif status == 'rejected':
        notify_workspace(ws, 'Plan has been rejected. Check comments for feedback.')

    return jsonify({"ok": True, "plan_status": status})


@bp.route("/api/ws/<project_id>/<path:branch>/phase", methods=["PUT"])
@with_workspace
def set_phase(db, ws, project):
    body = request.json or {}
    new_phase = body.get("phase", "").strip()
    if not new_phase:
        return jsonify({"error": t("api.error.phaseRequired")}), 400

    new_phase = normalize_phase(new_phase)
    if new_phase is None:
        return jsonify({"error": t("api.error.invalidPhase")}), 400

    old_phase = ws["phase"]
    db.execute("UPDATE workspaces SET phase = ? WHERE id = ?", (new_phase, ws["id"]))
    db.execute(
        "INSERT INTO phase_history (workspace_id, from_phase, to_phase, time) VALUES (?, ?, ?, ?)",
        (ws["id"], old_phase, new_phase, datetime.now().isoformat())
    )

    db.commit()
    return jsonify({"phase": new_phase, "previous_phase": old_phase})



@bp.route("/api/ws/<project_id>/<path:branch>/research/<int:research_id>/prove", methods=["POST"])
@with_workspace
def toggle_research_proven(db, ws, project, research_id):
    """Toggle research entry proven status. Body: {"proven": true/false}"""
    body = request.get_json(silent=True) or {}
    proven = body.get("proven", False)

    result = research_service.set_proven(
        db, research_id, ws["id"], proven,
        notes="Manual override via admin panel",
    )
    if "error" in result:
        return jsonify({"error": t("api.error.researchEntryNotFound")}), 404

    db.commit()
    return jsonify(result)



@bp.route("/api/ws/<project_id>/<path:branch>/research/<int:research_id>", methods=["DELETE"])
@with_workspace
def delete_research(db, ws, project, research_id):
    deleted = research_service.delete_research(db, research_id, ws["id"])

    if not deleted:
        return jsonify({"error": t("api.error.researchEntryNotFound")}), 404

    db.commit()
    return jsonify({"ok": True})
