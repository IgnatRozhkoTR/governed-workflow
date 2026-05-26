"""Phase advancement orchestrator using Phase objects.

Replaces hardcoded phase string routing with Phase registry lookups. Admin
token middleware enforces caller identity upstream of approve/reject, so no
per-request nonce is consulted here.
"""
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from advance.guards import GUARD_ORCHESTRATOR
from advance.phases import get_phase
from core.db import get_db_ctx, ws_field
from core.helpers import run_git
from core.i18n import t
from core.phase import is_templated
from core.terminal import notify_workspace
from services.advance_mode_service import get_mode_for_boundary
from services.phase_sequencer import full_phase_sequence, plan_from_workspace, resolve_phase_sequence

logger = logging.getLogger(__name__)

_COMMIT_PHASE_RE = re.compile(r'^3\.\d+\.4$')
_DEFAULT_MAX_FILES_PER_REVIEW = 100


class AdvanceBusinessRuleError(Exception):
    """Raised when a business-rule pre-flight check blocks a phase transition."""


_EXECUTION_START_RE = re.compile(r'^3\.\d+\.0$')
_PENDING_ADVANCE_ACTION_PATH = ".claude/state/pending-advance-action"


def _is_major_transition(old_phase: str, new_phase: str) -> bool:
    old = get_phase(old_phase)
    new = get_phase(new_phase)
    if not old or not new:
        return False
    return old.boundary_key != new.boundary_key


def _resolve_forward_target(ws, db, candidate: str) -> str | None:
    """Resolve the next phase the workspace should advance into.

    Returns the candidate unchanged when it is enabled AND differs from the
    workspace's current phase. When the candidate equals the current phase
    (module phases with no declared approve_target signal "walk onward") or
    when the candidate is disabled, walks forward through the full spliced
    sequence from the candidate's position and returns the first enabled
    phase. Falls back to returning the candidate when it is not in the
    sequence at all (e.g. an execution phase for an item that no longer
    exists in the plan). Returns ``None`` when the candidate is explicitly
    disabled and no enabled successor exists, so callers treat the
    transition as a no-op instead of silently writing a disabled phase.
    """
    plan = plan_from_workspace(ws)
    enabled, _ = resolve_phase_sequence(db, ws, plan)
    current = ws["phase"]
    if candidate != current and candidate in enabled:
        return candidate

    full = full_phase_sequence(plan)
    try:
        start_idx = full.index(candidate)
    except ValueError:
        return candidate

    for phase_id in full[start_idx + 1:]:
        if phase_id in enabled:
            return phase_id

    logger.warning(
        "No enabled phase after candidate=%s (current=%s) for workspace %s; advance is a no-op.",
        candidate, current, ws["id"],
    )
    return None


def is_user_gate(phase_str: str) -> bool:
    """Check whether a phase requires explicit user approval."""
    phase = get_phase(phase_str)
    return phase.is_user_gate if phase else False


def check_progress(workspace_id, phase_key):
    """Verify that a progress entry exists for the given phase key."""
    with get_db_ctx() as db:
        row = db.execute(
            "SELECT summary FROM progress_entries WHERE workspace_id = ? AND phase = ?",
            (workspace_id, phase_key)
        ).fetchone()
        return bool(row and row["summary"].strip())


def _lazy_init_execution_checkpoint(db, ws, new_phase: str) -> None:
    """When entering a fresh execution start (3.N.0), set the commit checkpoint.

    Only fires when the workspace has no ``last_confirmed_commit`` yet. The
    checkpoint is the current HEAD of ``ws["working_dir"]`` — that is the
    base from which the next commit must descend.
    """
    if not _EXECUTION_START_RE.match(new_phase):
        return
    if ws_field(ws, "last_confirmed_commit", None):
        return

    ok, stdout, _ = run_git(ws["working_dir"], "rev-parse", "HEAD")
    if not ok:
        return
    head = stdout.strip()
    if not head:
        return

    db.execute(
        "UPDATE workspaces SET last_confirmed_commit = ? WHERE id = ?",
        (head, ws["id"])
    )


def _max_files_for_review() -> int:
    raw = os.environ.get("GOVERNED_WORKFLOW_MAX_FILES_PER_REVIEW", str(_DEFAULT_MAX_FILES_PER_REVIEW))
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_FILES_PER_REVIEW


def _check_review_file_count(ws) -> None:
    """Raise AdvanceBusinessRuleError if the branch diff size exceeds the review limit.

    Called only when transitioning INTO phase 4.0. Diff-filter failures are
    swallowed (graceful degradation) — we never block a legitimate advance
    because the count couldn't be determined.
    """
    from services import diff_filter

    working_dir = ws_field(ws, "working_dir")
    if not working_dir:
        return
    base_ref = diff_filter.resolve_review_base(
        Path(working_dir), ws_field(ws, "source_branch") or "main"
    )
    try:
        count = diff_filter.count_modified(
            repo_path=Path(working_dir),
            base_ref=base_ref,
            head_ref="HEAD",
        )
    except Exception:
        logger.exception("pre-flight file count failed; allowing advance")
        return
    limit = _max_files_for_review()
    if count > limit:
        raise AdvanceBusinessRuleError(
            f"Cannot advance to 4.0: branch diff contains {count} reviewable files "
            f"(limit {limit}). Set GOVERNED_WORKFLOW_MAX_FILES_PER_REVIEW to override, "
            f"or split the work into smaller branches."
        )


def _maybe_write_advance_action(db, ws, new_phase: str) -> None:
    """Write pending-advance-action file when crossing a boundary_key boundary.

    Only fires for compact/clear modes; none and missing rows are no-ops.
    Write failures are swallowed so they never block a phase transition.
    """
    old_phase = ws["phase"]
    if not _is_major_transition(old_phase, new_phase):
        return

    new = get_phase(new_phase)
    if not new:
        return

    project_id = ws["project_id"]
    mode = get_mode_for_boundary(db, project_id, new.boundary_key)
    if mode not in ("compact", "clear"):
        return

    working_dir = ws_field(ws, "working_dir")

    if not working_dir or not os.path.isdir(working_dir):
        logger.warning(
            "Cannot write pending-advance-action for workspace %s: working_dir %r is missing or not a directory.",
            ws["id"],
            working_dir,
        )
        return

    action_path = os.path.join(working_dir, _PENDING_ADVANCE_ACTION_PATH)
    try:
        os.makedirs(os.path.dirname(action_path), exist_ok=True)
        with open(action_path, "w") as fh:
            fh.write(mode)
    except Exception:
        logger.warning(
            "Failed to write pending-advance-action for workspace %s (mode=%s); phase transition continues.",
            ws["id"],
            mode,
            exc_info=True,
        )


def transition_phase(db, ws, new_phase, commit_hash=None):
    """Shared phase transition: update phase and record history.

    Returns a list of zero-argument callables that MUST be invoked after
    ``db.commit()`` succeeds (e.g. write action file, start pipeline thread).
    Returns an empty list when the phase was already changed by a concurrent
    request (optimistic lock via WHERE phase = current) — callers must check
    with ``if transition_phase(...) is not None``.

    When the FROM phase is a commit phase (``3.N.4``) and a ``commit_hash`` is
    provided, ``workspaces.last_confirmed_commit`` is advanced to that hash so
    subsequent progression-guard checks compare against the newest confirmed
    checkpoint.

    When the TO phase is a fresh execution start (``3.N.0``) and
    ``last_confirmed_commit`` is still NULL, the current HEAD is recorded as
    the checkpoint so the first commit submitted in the execution can be
    validated against a concrete base.
    """
    if new_phase == "4.0":
        _check_review_file_count(ws)

    rows = db.execute(
        "UPDATE workspaces SET phase = ? WHERE id = ? AND phase = ?",
        (new_phase, ws["id"], ws["phase"])
    ).rowcount
    if rows == 0:
        return None

    db.execute(
        "INSERT INTO phase_history (workspace_id, from_phase, to_phase, time, commit_hash) VALUES (?, ?, ?, ?, ?)",
        (ws["id"], ws["phase"], new_phase, datetime.now().isoformat(), commit_hash)
    )

    if commit_hash and _COMMIT_PHASE_RE.match(ws["phase"]):
        db.execute(
            "UPDATE workspaces SET last_confirmed_commit = ? WHERE id = ?",
            (commit_hash, ws["id"])
        )

    _lazy_init_execution_checkpoint(db, ws, new_phase)

    post_commit: list = []
    ws_snapshot = dict(ws)
    post_commit.append(lambda: _maybe_write_advance_action(db, ws_snapshot, new_phase))
    if new_phase == "4.0":
        post_commit.append(lambda: _start_review_pipeline(ws_snapshot))

    return post_commit


def _start_review_pipeline(ws) -> None:
    """Spawn the background headless review pipeline.

    Disabled when ``GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE`` is truthy
    (used by tests that do not want to fork a real Claude subprocess).
    Failures here never block the phase transition.
    """
    if os.environ.get("GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE"):
        return

    working_dir = ws_field(ws, "working_dir")
    if not working_dir:
        return

    try:
        from services import review_pipeline_service

        review_pipeline_service.start_in_background(
            workspace_id=ws["id"],
            project_path=Path(working_dir),
            base_branch=ws_field(ws, "source_branch") or "main",
        )
    except Exception:
        logger.exception(
            "failed to start review pipeline for workspace %s", ws["id"]
        )


def _notify_yolo_approve(ws, phase):
    """Send a YOLO auto-approval notification to the tmux session."""
    try:
        from core.terminal import send_prompt, session_name, session_exists
        name = session_name(ws["project_id"], ws["sanitized_branch"])
        if session_exists(name):
            send_prompt(name, f"[YOLO] Auto-approved phase {phase}. Proceeding.")
    except Exception:
        logger.warning("Failed to send YOLO auto-approve notification", exc_info=True)


def approve_gate(ws, commit_message=None):
    """Approve a user gate. Returns a result dict with an embedded status_code key.

    Admin-token middleware enforces caller identity upstream of this function.
    """
    locale = ws["locale"]
    phase_str = ws["phase"]

    phase = get_phase(phase_str)
    if not phase or not phase.is_user_gate:
        return {"error": t("gate.error.notAtUserGate", locale), "status_code": 400}

    yolo_mode = ws_field(ws, "yolo_mode", 0)
    if not yolo_mode:
        guard_results = GUARD_ORCHESTRATOR.evaluate_all(phase_str, ws, {})
        rejected = [r for r in guard_results if r["status"] == "rejected"]
        if rejected:
            return {"error": rejected[0]["message"], "guard_errors": rejected, "status_code": 422}

    candidate = phase.approve_target
    if not candidate:
        return {"error": t("gate.error.unknownGate", locale), "status_code": 400}

    with get_db_ctx() as db:
        new_phase = _resolve_forward_target(ws, db, candidate)
        if new_phase is None:
            return {
                "error": t("gate.error.noEnabledSuccessor", locale, candidate=candidate),
                "status_code": 409,
            }

        phase.on_approve(ws, {"commit_message": commit_message} if commit_message else {}, db)

        try:
            post_commit = transition_phase(db, ws, new_phase)
        except AdvanceBusinessRuleError as exc:
            return {"error": str(exc), "status_code": 422}
        if post_commit is None:
            return {"error": t("gate.error.phaseAlreadyChanged", locale), "status_code": 409}

        db.commit()
        for callback in post_commit:
            callback()
        return {"phase": new_phase, "previous_phase": phase_str, "status": "ok", "status_code": 200}


def reject_gate(ws, comments=""):
    """Reject a user gate. Returns a result dict with an embedded status_code key.

    Admin-token middleware enforces caller identity upstream of this function.
    """
    locale = ws["locale"]
    phase_str = ws["phase"]

    phase = get_phase(phase_str)
    if not phase or not phase.is_user_gate:
        return {"error": t("gate.error.notAtUserGate", locale), "status_code": 400}

    candidate = phase.reject_target
    if not candidate:
        return {"error": t("gate.error.unknownGate", locale), "status_code": 400}

    with get_db_ctx() as db:
        new_phase = _resolve_forward_target(ws, db, candidate)
        if new_phase is None:
            return {
                "error": t("gate.error.noEnabledSuccessor", locale, candidate=candidate),
                "status_code": 409,
            }

        try:
            post_commit = transition_phase(db, ws, new_phase)
        except AdvanceBusinessRuleError as exc:
            return {"error": str(exc), "status_code": 422}
        if post_commit is None:
            return {"error": t("gate.error.phaseAlreadyChanged", locale), "status_code": 409}

        if comments:
            db.execute(
                "INSERT INTO discussions (workspace_id, scope, target, text, author, status, created_at) "
                "VALUES (?, 'phase', ?, ?, 'user', 'open', ?)",
                (ws["id"], f"reject:{phase_str}", comments, datetime.now().isoformat())
            )

        db.commit()
        for callback in post_commit:
            callback()
        return {"phase": new_phase, "previous_phase": phase_str, "status": "rejected", "status_code": 200}


def perform_advance(ws, project_path, body=None):
    """Core advance logic. Returns (result_dict, http_status_code).

    Can be called from Flask route or MCP tool.
    Manages its own DB connection for the transaction.
    """
    body = body or {}
    phase_str = ws["phase"]
    locale = ws["locale"]

    if is_templated(phase_str):
        return {"error": t("advance.error.noAdvancerForPhase", locale, phase=phase_str)}, 400

    phase = get_phase(phase_str)
    if not phase:
        return {"error": t("advance.error.noAdvancerForPhase", locale, phase=phase_str)}, 400

    if phase.is_user_gate:
        yolo = ws_field(ws, "yolo_mode", 0)
        if yolo:
            approve_result = approve_gate(ws)
            status_code = approve_result.pop("status_code", 200)
            if status_code == 200:
                _notify_yolo_approve(ws, phase_str)
                return approve_result, status_code
        return {"error": t("advance.error.awaitingUserApproval", locale), "phase": phase_str}, 409

    yolo_mode = ws_field(ws, "yolo_mode", 0)
    if not yolo_mode:
        ok, details = phase.validate(ws, body, project_path)
        if not ok:
            return {"phase": phase_str, "status": "blocked", **details}, 422

        required_key = phase.progress_key(ws)
        if required_key and not check_progress(ws["id"], required_key):
            return {
                "phase": phase_str,
                "status": "blocked",
                "message": t("advance.error.noProgress", locale, phase=required_key, next=phase.next_phase(ws)),
            }, 422

        guard_results = GUARD_ORCHESTRATOR.evaluate_all(phase_str, ws, body)
        rejected = [r for r in guard_results if r["status"] == "rejected"]
        if rejected:
            return {"phase": phase_str, "status": "blocked", "guard_errors": rejected}, 422

    candidate = phase.next_phase(ws)

    with get_db_ctx() as db:
        new_phase = _resolve_forward_target(ws, db, candidate)
        if new_phase is None:
            return {
                "phase": phase_str,
                "status": "blocked",
                "message": t("advance.error.noEnabledSuccessor", locale, candidate=candidate),
            }, 409

        try:
            post_commit = transition_phase(db, ws, new_phase, commit_hash=body.get("commit_hash"))
        except AdvanceBusinessRuleError as exc:
            return {"error": str(exc), "status": "blocked"}, 422
        if post_commit is None:
            return {"error": t("advance.error.phaseAlreadyChanged", locale)}, 409

        db.commit()
        for callback in post_commit:
            callback()

        yolo_enabled = ws_field(ws, "yolo_mode", 0)
        if is_user_gate(new_phase) and yolo_enabled:
            ws_fresh = db.execute(
                "SELECT * FROM workspaces WHERE project_id = ? AND sanitized_branch = ?",
                (ws["project_id"], ws["sanitized_branch"])
            ).fetchone()
            if ws_fresh:
                approve_result = approve_gate(ws_fresh)
                approve_status = approve_result.pop("status_code", 200)
                if approve_status == 200:
                    _notify_yolo_approve(ws_fresh, new_phase)
                    return approve_result, approve_status

        code = 202 if is_user_gate(new_phase) else 200
        result = {
            "phase": new_phase,
            "previous_phase": phase_str,
            "message": phase.success_message(ws, new_phase),
            "status": "awaiting_approval" if code == 202 else "ok",
        }
        if code == 202:
            notify_workspace(ws, "Phase requires your approval. Check the admin panel.")
        return result, code
