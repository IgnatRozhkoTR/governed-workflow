"""Tests for cross-cutting advance guards."""
import json

from advance.guards import GUARD_ORCHESTRATOR, ResearchProvenGuard, ReviewGuard
from advance.orchestrator import perform_advance
from testing_utils import set_phase, add_progress, add_research, make_plan_json, add_comment
from core.db import get_db


def _get_ws_row(ws_id):
    db = get_db()
    row = db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    db.close()
    return row


# ── Guard unit tests (evaluate directly) ─────────────────────────────────────

def test_guard_skip_at_exempt_phase(workspace, project):
    """Guard returns 'skip' at exempt phases."""
    guard = ResearchProvenGuard()
    add_research(workspace["id"], topic="Unproven", proven=0)
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("0", ws, {})
    assert result["status"] == "skip"
    assert result["guard"] == "research_proven"


def test_guard_approved_no_research(workspace, project):
    """No research entries — guard approves."""
    guard = ResearchProvenGuard()
    set_phase(workspace["id"], "1.3")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("1.3", ws, {})
    assert result["status"] == "approved"


def test_guard_approved_all_proven(workspace, project):
    """All research proven — guard approves."""
    guard = ResearchProvenGuard()
    add_research(workspace["id"], topic="Good", proven=1)
    set_phase(workspace["id"], "1.3")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("1.3", ws, {})
    assert result["status"] == "approved"


def test_guard_rejected_unproven(workspace, project):
    """Unproven research — guard rejects."""
    guard = ResearchProvenGuard()
    add_research(workspace["id"], topic="Unproven", proven=0)
    set_phase(workspace["id"], "1.3")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("1.3", ws, {})
    assert result["status"] == "rejected"
    assert "unproven" in result


def test_guard_rejected_disproved(workspace, project):
    """Rejected research — guard rejects with rejected list."""
    guard = ResearchProvenGuard()
    add_research(workspace["id"], topic="Bad", proven=-1)
    set_phase(workspace["id"], "2.0")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("2.0", ws, {})
    assert result["status"] == "rejected"
    assert "rejected" in result
    assert len(result["rejected"]) == 1


# ── Orchestrator tests ───────────────────────────────────────────────────────

def test_orchestrator_collects_all_results(workspace, project):
    """Orchestrator returns results from all guards."""
    ws = _get_ws_row(workspace["id"])
    results = GUARD_ORCHESTRATOR.evaluate_all("0", ws, {})
    assert isinstance(results, list)
    assert len(results) >= 1  # at least ResearchProvenGuard
    assert all("status" in r for r in results)


# ── Integration with perform_advance ─────────────────────────────────────────

def test_advance_blocked_by_guard_returns_errors_list(workspace, project):
    """perform_advance returns guard_errors list on rejection."""
    add_research(workspace["id"], topic="Unproven", proven=0)
    set_phase(workspace["id"], "1.3")
    add_progress(workspace["id"], "1.3", "Impact done")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422
    assert "guard_errors" in result
    assert isinstance(result["guard_errors"], list)
    assert any(e["guard"] == "research_proven" for e in result["guard_errors"])


def test_advance_passes_guards_when_all_approved(workspace, project):
    """perform_advance succeeds when all guards approve — 1.3 advances to 1.4 (user gate, 202)."""
    add_research(workspace["id"], topic="Good", proven=1)
    set_phase(workspace["id"], "1.3")
    add_progress(workspace["id"], "1.3", "Impact done")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 202
    assert result["phase"] == "1.4"
    assert result["status"] == "awaiting_approval"


def test_advance_at_exempt_phase_ignores_unproven(workspace, project):
    """Guards returning 'skip' don't block advancement."""
    add_research(workspace["id"], topic="Unproven", proven=0)
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "1.0"


# ── PlanApprovedGuard tests ──────────────────────────────────────────────────

def test_plan_guard_skip_early_phases(workspace, project):
    """Plan guard skips at phases before planning."""
    from advance.guards import PlanApprovedGuard
    guard = PlanApprovedGuard()
    ws = _get_ws_row(workspace["id"])
    for phase in ("0", "1.0", "1.1", "1.2", "1.3"):
        result = guard.evaluate(phase, ws, {})
        assert result["status"] == "skip", f"Expected skip at phase {phase}"


def test_plan_guard_approved_no_plan(workspace, project):
    """No plan exists — guard approves (nothing to check)."""
    from advance.guards import PlanApprovedGuard
    guard = PlanApprovedGuard()
    set_phase(workspace["id"], "2.0")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("2.0", ws, {})
    assert result["status"] == "approved"


def test_plan_guard_rejected_unapproved(workspace, project):
    """Plan exists but not approved — guard rejects."""
    from advance.guards import PlanApprovedGuard
    guard = PlanApprovedGuard()
    plan = make_plan_json(1)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="pending")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("2.0", ws, {})
    assert result["status"] == "rejected"
    assert result["guard"] == "plan_approved"


def test_plan_guard_approved_when_approved(workspace, project):
    """Plan approved — guard passes."""
    from advance.guards import PlanApprovedGuard
    guard = PlanApprovedGuard()
    plan = make_plan_json(1)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("2.0", ws, {})
    assert result["status"] == "approved"


# ── PlanApprovedGuard covers execution phases (formerly ScopeApprovedGuard) ──

def test_plan_guard_rejected_unapproved_at_execution(workspace, project):
    """Plan not approved during execution — the single plan guard rejects.

    PlanApprovedGuard now covers what ScopeApprovedGuard used to: execution and
    review phases are gated by plan approval (scope is part of the plan).
    """
    from advance.guards import PlanApprovedGuard
    guard = PlanApprovedGuard()
    set_phase(workspace["id"], "3.1.0", plan_json=make_plan_json(1), plan_status="pending")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("3.1.0", ws, {})
    assert result["status"] == "rejected"
    assert result["guard"] == "plan_approved"


def test_plan_guard_approved_at_execution(workspace, project):
    """Plan approved during execution — the plan guard passes."""
    from advance.guards import PlanApprovedGuard
    guard = PlanApprovedGuard()
    set_phase(workspace["id"], "3.1.0", plan_json=make_plan_json(1), plan_status="approved")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("3.1.0", ws, {})
    assert result["status"] == "approved"


def test_set_plan_revokes_only_plan_status(workspace, project):
    """set_plan resets plan_status to pending; there is no separate scope status."""
    from services import plan_service
    set_phase(workspace["id"], "2.0", plan_status="approved")
    ws = _get_ws_row(workspace["id"])

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, json.loads(make_plan_json(1)))
        db.commit()
    finally:
        db.close()

    assert result["plan_status"] == "pending"
    assert "scope_status" not in result
    assert _get_ws_row(workspace["id"])["plan_status"] == "pending"


# ── ReviewGuard tests ────────────────────────────────────────────────────────

def test_review_guard_skip_at_non_gate_phases(workspace, project):
    """Review guard skips at all phases except user gates 3.N.3 and 4.2."""
    guard = ReviewGuard()
    add_comment(workspace["id"], scope="review", text="Unresolved finding", resolution="open")
    ws = _get_ws_row(workspace["id"])
    for phase in ("0", "1.0", "1.1", "1.2", "1.3", "2.0", "2.1",
                   "3.1.0", "3.1.1", "3.1.2", "3.1.4", "4.0", "4.1"):
        result = guard.evaluate(phase, ws, {})
        assert result["status"] == "skip", f"Expected skip at phase {phase}"


def test_review_guard_approved_no_items(workspace, project):
    """No review items — guard approves at code review gate."""
    guard = ReviewGuard()
    set_phase(workspace["id"], "3.1.3")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("3.1.3", ws, {})
    assert result["status"] == "approved"


def test_review_guard_rejected_at_code_review_gate(workspace, project):
    """Unresolved review comments block approval at 3.N.3."""
    guard = ReviewGuard()
    add_comment(workspace["id"], scope="review", text="Open finding", resolution="open")
    set_phase(workspace["id"], "3.1.3")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("3.1.3", ws, {})
    assert result["status"] == "rejected"
    assert result["unresolved_count"] == 1


def test_review_guard_approved_all_resolved_at_gate(workspace, project):
    """All review items resolved — guard approves at 4.2."""
    guard = ReviewGuard()
    add_comment(workspace["id"], scope="review", text="Fixed finding", resolution="fixed")
    set_phase(workspace["id"], "4.2")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("4.2", ws, {})
    assert result["status"] == "approved"


def test_review_guard_rejects_at_final_approval(workspace, project):
    """Guard blocks at 4.2 when review items are unresolved."""
    guard = ReviewGuard()
    add_comment(workspace["id"], scope="review", text="Blocking comment", resolution="open")
    set_phase(workspace["id"], "4.2")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("4.2", ws, {})
    assert result["status"] == "rejected"


def test_review_guard_does_not_block_fixes_to_review(workspace, project):
    """Agent can advance from 3.N.2 (fixes) to 3.N.3 (review) with unresolved items."""
    guard = ReviewGuard()
    add_comment(workspace["id"], scope="review", text="Open finding", resolution="fixed")
    set_phase(workspace["id"], "3.1.2")
    ws = _get_ws_row(workspace["id"])
    result = guard.evaluate("3.1.2", ws, {})
    assert result["status"] == "skip"


def test_advance_blocked_by_review_guard_at_gate(workspace, project):
    """approve_gate blocked by ReviewGuard with unresolved review item at 4.2."""
    add_comment(workspace["id"], scope="review", text="Blocking finding", resolution="open")
    set_phase(workspace["id"], "4.2", plan_status="approved")
    add_research(workspace["id"], topic="Good", proven=1)
    ws = _get_ws_row(workspace["id"])

    from advance.orchestrator import approve_gate
    result = approve_gate(ws)
    assert "error" in result
    assert "guard_errors" in result
