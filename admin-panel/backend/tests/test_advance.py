"""Tests for advance endpoints (approve/reject) and perform_advance advancers."""
import advance.orchestrator as orchestrator

from testing_utils import set_phase, add_progress, add_research, add_discussion, add_review_issue, add_criterion, add_comment, make_plan_json


# ── Approve/Reject endpoint tests ────────────────────────────────────────────


def test_approve_at_plan_review(workspace, project):
    """Phase 2.0 auto-advances directly to first execution phase when scope and plan are both approved."""
    plan = make_plan_json(2)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved", scope_status="approved")
    add_progress(workspace["id"], "2", "Planning done")
    add_criterion(workspace["id"], status="accepted")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "3.1.0"


def test_approve_at_code_review(client, workspace):
    """Approve at 3.1.3 → advances to 3.1.4 (commit)."""
    plan = make_plan_json(1)
    set_phase(workspace["id"], "3.1.3", plan_json=plan,
              plan_status="approved", scope_status="approved")

    r = client.post("/api/ws/test-project/feature/test/approve", json={})
    assert r.status_code == 200
    assert r.json["phase"] == "3.1.4"


def test_approve_at_final_gate(client, workspace):
    """Approve at 4.2 → phase 5.1 (Reflection)."""
    plan = make_plan_json(1)
    set_phase(workspace["id"], "4.2", plan_json=plan,
              plan_status="approved", scope_status="approved")

    r = client.post("/api/ws/test-project/feature/test/approve", json={})
    assert r.status_code == 200
    assert r.json["phase"] == "5.1"


def test_approve_at_gate_no_token_field_needed(client, workspace):
    """Admin-token middleware is the real identity check, so approve works
    with an empty body (no token field at all)."""
    set_phase(workspace["id"], "1.4")

    r = client.post("/api/ws/test-project/feature/test/approve", json={})
    assert r.status_code == 200
    assert r.json["phase"] == "2.0"


def test_approve_not_at_gate(client, workspace):
    r = client.post("/api/ws/test-project/feature/test/approve", json={})
    assert r.status_code == 400


def test_reject_at_gate_no_token_field_needed(client, workspace):
    """Reject works with only a ``comments`` field — no token required."""
    set_phase(workspace["id"], "1.4")

    r = client.post(
        "/api/ws/test-project/feature/test/reject",
        json={"comments": "back to research"},
    )
    assert r.status_code == 200
    assert r.json["phase"] == "1.1"


def test_reject_at_plan_review(client, workspace):
    """Reject at phase 1.4 (preparation review) → goes back to 1.1."""
    set_phase(workspace["id"], "1.4")

    r = client.post("/api/ws/test-project/feature/test/reject", json={})
    assert r.status_code == 200
    assert r.json["phase"] == "1.1"


def test_reject_at_code_review(client, workspace):
    set_phase(workspace["id"], "3.1.3")

    r = client.post("/api/ws/test-project/feature/test/reject", json={})
    assert r.status_code == 200
    assert r.json["phase"] == "3.1.2"


def test_reject_at_final_gate(client, workspace):
    set_phase(workspace["id"], "4.2")

    r = client.post("/api/ws/test-project/feature/test/reject", json={})
    assert r.status_code == 200
    assert r.json["phase"] == "4.1"


def test_reject_with_comments(client, workspace):
    set_phase(workspace["id"], "4.2")

    r = client.post(
        "/api/ws/test-project/feature/test/reject",
        json={"comments": "Fix the plan"},
    )
    assert r.status_code == 200

    from core.db import get_db
    db = get_db()
    comment = db.execute(
        "SELECT * FROM discussions WHERE workspace_id = ? AND scope = 'phase'", (workspace["id"],)
    ).fetchone()
    db.close()
    assert comment["text"] == "Fix the plan"
    assert comment["scope"] == "phase"


# ── Advancer tests (perform_advance directly) ─────────────────────────────────


from advance.orchestrator import perform_advance
from core.db import get_db


def _get_ws_row(ws_id):
    """Fetch a fresh workspace row from DB."""
    db = get_db()
    row = db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    db.close()
    return row


def test_init_advancer(workspace, project):
    """Phase 0 → 1.0 always succeeds."""
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "1.0"


def test_assessment_blocked_without_progress(workspace, project):
    set_phase(workspace["id"], "1.0")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422


def test_assessment_passes_with_progress(workspace, project):
    set_phase(workspace["id"], "1.0")
    add_progress(workspace["id"], "1.0", "Assessment done")
    add_discussion(workspace["id"], type="research")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "1.1"


def test_research_blocked_no_entries(workspace, project):
    set_phase(workspace["id"], "1.1")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422


def test_research_passes(workspace, project):
    set_phase(workspace["id"], "1.1")
    disc_id = add_discussion(workspace["id"], type="research")
    add_research(workspace["id"], discussion_id=disc_id)
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"no_further_research_needed": True})
    assert code == 200
    assert result["phase"] == "1.2"


def test_prover_blocked_unproven(workspace, project):
    set_phase(workspace["id"], "1.2")
    add_research(workspace["id"], proven=0)
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422


def test_prover_blocked_rejected(workspace, project):
    set_phase(workspace["id"], "1.2")
    add_research(workspace["id"], proven=-1)
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422


def test_prover_passes(workspace, project):
    set_phase(workspace["id"], "1.2")
    add_research(workspace["id"], proven=1)
    add_progress(workspace["id"], "1", "Research done")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "1.3"


def test_impact_analysis_passes(workspace, project):
    set_phase(workspace["id"], "1.3")
    add_progress(workspace["id"], "1.3", "Impact analyzed")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 202
    assert result["phase"] == "1.4"
    assert result["status"] == "awaiting_approval"


def test_preparation_review_is_user_gate(workspace, project):
    """Phase 1.4 is a user gate — perform_advance returns 409."""
    set_phase(workspace["id"], "1.4")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 409
    assert "error" in result


def test_approve_at_preparation_review(client, workspace):
    """Approve at phase 1.4 → advances to 2.0."""
    set_phase(workspace["id"], "1.4")

    r = client.post("/api/ws/test-project/feature/test/approve", json={})
    assert r.status_code == 200
    assert r.json["phase"] == "2.0"


def test_reject_at_preparation_review(client, workspace):
    """Reject at phase 1.4 → goes back to 1.1."""
    set_phase(workspace["id"], "1.4")

    r = client.post("/api/ws/test-project/feature/test/reject", json={})
    assert r.status_code == 200
    assert r.json["phase"] == "1.1"


def test_plan_blocked_no_plan(workspace, project):
    set_phase(workspace["id"], "2.0")
    add_progress(workspace["id"], "2", "Planning done")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422


def test_plan_passes(workspace, project):
    plan = make_plan_json(2)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved", scope_status="approved")
    add_progress(workspace["id"], "2", "Planning done")
    add_criterion(workspace["id"], status="accepted")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "3.1.0"


def test_plan_blocked_by_pending_criteria(workspace, project):
    """PlanAdvancer at 2.0 blocks when proposed criteria exist."""
    plan = make_plan_json(1)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved", scope_status="approved")
    add_progress(workspace["id"], "2", "Planning done")
    add_criterion(workspace["id"], status="proposed")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422
    assert "acceptance criteria" in result["error"].lower()


def test_user_gate_blocks_advance(workspace, project):
    set_phase(workspace["id"], "1.4")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 409


# ── AgenticReviewAdvancer (phase 4.0) ──────────────────────────────────────────

import json
from pathlib import Path
from testing_utils import _git, GIT_ENV


def _setup_execution_phase(ws_id, phase, num_plan_phases=3):
    """Set up workspace for an execution phase with all required fields."""
    plan = make_plan_json(num_plan_phases)
    scope = {f"3.{n}": {"must": ["src/"], "may": ["tests/"]} for n in range(1, num_plan_phases + 1)}
    set_phase(
        ws_id, phase,
        plan_json=plan,
        plan_status="approved",
        scope_status="approved",
        scope_json=json.dumps(scope),
    )


def test_agentic_review_blocked_without_progress(workspace, project):
    """Phase 4.0 blocks without a progress entry."""
    plan = make_plan_json(1)
    set_phase(
        workspace["id"], "4.0",
        plan_json=plan,
        plan_status="approved",
        scope_status="approved",
    )

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422
    assert result["status"] == "blocked"


def test_agentic_review_passes_with_progress(workspace, project):
    """Phase 4.0 advances to 4.1 when progress entry exists."""
    plan = make_plan_json(1)
    set_phase(
        workspace["id"], "4.0",
        plan_json=plan,
        plan_status="approved",
        scope_status="approved",
    )
    add_progress(workspace["id"], "4.0", "Agentic review completed")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "4.1"


# ── AddressFixAdvancer (phase 4.1) ─────────────────────────────────────────────


def _add_review_issue_row(ws_id, file_path="src/main.py", code_snippet="def main():",
                          resolution="open"):
    """Insert a review issue with full control over resolution."""
    from datetime import datetime
    now = datetime.now().isoformat()
    db = get_db()
    cursor = db.execute(
        "INSERT INTO review_issues (workspace_id, file_path, line_start, line_end, "
        "severity, description, code_snippet, resolution, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ws_id, file_path, 1, 5, "major", "Test issue", code_snippet, resolution, now)
    )
    issue_id = cursor.lastrowid
    db.commit()
    db.close()
    return issue_id


def test_address_fix_blocked_without_progress(workspace, project):
    """Phase 4.1 blocks without a progress entry for '4'."""
    plan = make_plan_json(1)
    set_phase(
        workspace["id"], "4.1",
        plan_json=plan,
        plan_status="approved",
        scope_status="approved",
    )

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422
    assert result["status"] == "blocked"


def test_address_fix_passes_no_issues(workspace, project):
    """Phase 4.1 advances to 4.2 when progress exists and no review issues."""
    plan = make_plan_json(1)
    set_phase(
        workspace["id"], "4.1",
        plan_json=plan,
        plan_status="approved",
        scope_status="approved",
    )
    add_progress(workspace["id"], "4", "All fixes addressed")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 202
    assert result["phase"] == "4.2"


def test_address_fix_advances_with_unresolved_review(workspace, project):
    """Phase 4.1 can advance to 4.2 even with unresolved reviews — user resolves at gate."""
    plan = make_plan_json(1)
    set_phase(
        workspace["id"], "4.1",
        plan_json=plan,
        plan_status="approved",
        scope_status="approved",
    )
    add_progress(workspace["id"], "4", "Addressing fixes")
    add_comment(workspace["id"], scope="review", text="Review finding", resolution="fixed")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 202
    assert result["phase"] == "4.2"


def test_address_fix_passes_all_fixed(workspace, project):
    """Phase 4.1 advances when all issues are fixed and code changed."""
    plan = make_plan_json(1)
    set_phase(
        workspace["id"], "4.1",
        plan_json=plan,
        plan_status="approved",
        scope_status="approved",
    )
    add_progress(workspace["id"], "4", "All fixes addressed")
    # code_snippet is "old buggy code" which does NOT exist in any file
    _add_review_issue_row(
        workspace["id"],
        file_path="src/main.py",
        code_snippet="old buggy code that was removed",
        resolution="fixed",
    )

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 202
    assert result["phase"] == "4.2"


# ── ExecutionAdvancer (phase 3.N.K) ────────────────────────────────────────────


def test_execution_implementation_blocked_no_changes(workspace, project):
    """Phase 3.1.0 blocks when no git changes match must-scope."""
    _setup_execution_phase(workspace["id"], "3.1.0")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422
    assert "must-scope" in result["message"]


def test_execution_implementation_passes_with_changes(workspace, project):
    """Phase 3.1.0 advances to 3.1.1 when files matching must-scope are committed."""
    _setup_execution_phase(workspace["id"], "3.1.0")

    working_dir = workspace["working_dir"]
    _git(working_dir, "checkout", "-b", "feature/test")
    src_dir = Path(working_dir) / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "feature.py").write_text("def feature():\n    return True\n")
    _git(working_dir, "add", ".")
    _git(working_dir, "commit", "-m", "Add feature implementation")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "3.1.1"


def _add_verification_run(ws_id, phase, status):
    """Insert a completed verification run so VerificationPhase.next_phase can route off it."""
    db = get_db()
    try:
        now = datetime.now().isoformat()
        db.execute(
            "INSERT INTO verification_runs (workspace_id, phase, status, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ws_id, phase, status, now, now),
        )
        db.commit()
    finally:
        db.close()


def test_execution_validation_routes_to_review(workspace, project):
    """Phase 3.1.1 routes to 3.1.3 (code review gate) when verification passed."""
    _setup_execution_phase(workspace["id"], "3.1.1")
    _add_verification_run(workspace["id"], "3.1.1", "passed")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 202
    assert result["phase"] == "3.1.3"


def test_execution_validation_routes_to_review_when_no_verification_run(workspace, project):
    """Phase 3.1.1 defaults to 3.1.3 (clean) when no verification run exists."""
    _setup_execution_phase(workspace["id"], "3.1.1")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 202
    assert result["phase"] == "3.1.3"


def test_execution_validation_routes_to_fixes(workspace, project):
    """Phase 3.1.1 routes to 3.1.2 (fixes) when verification failed."""
    _setup_execution_phase(workspace["id"], "3.1.1")
    _add_verification_run(workspace["id"], "3.1.1", "failed")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "3.1.2"


def test_execution_commit_blocked_no_hash(workspace, project):
    """Phase 3.1.4 blocks when no commit_hash is provided."""
    _setup_execution_phase(workspace["id"], "3.1.4")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={})
    assert code == 422
    assert "commit_hash" in result["message"]


def test_execution_commit_blocked_invalid_hash(workspace, project):
    """Phase 3.1.4 blocks when an invalid commit_hash is provided."""
    _setup_execution_phase(workspace["id"], "3.1.4")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": "deadbeef123"})
    assert code == 422
    assert "not found" in result["message"]


def test_execution_commit_passes(workspace, project):
    """Phase 3.1.4 advances when a valid commit hash and progress are provided."""
    _setup_execution_phase(workspace["id"], "3.1.4")
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    working_dir = workspace["working_dir"]
    src_dir = Path(working_dir) / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "committed.py").write_text("print('committed')\n")
    _git(working_dir, "add", ".")
    _git(working_dir, "commit", "-m", "Commit for sub-phase")

    import subprocess
    commit_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=working_dir,
        capture_output=True,
        text=True,
    ).stdout.strip()

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": commit_hash})
    assert code == 200
    assert result["phase"] == "3.2.0"


# ── ExecutionAdvancer validate_all integration (acceptance criteria) ─────────


def _make_commit(working_dir):
    """Create a dummy commit and return its hash."""
    import subprocess
    src_dir = Path(working_dir) / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "committed.py").write_text(f"print('commit {datetime.now().isoformat()}')\n")
    _git(working_dir, "add", ".")
    _git(working_dir, "commit", "-m", "Test commit")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=working_dir,
        capture_output=True,
        text=True,
    ).stdout.strip()


from datetime import datetime


def test_last_commit_blocked_by_failing_criteria(workspace, project):
    """Last sub-phase commit is blocked when an accepted criterion fails validation."""
    _setup_execution_phase(workspace["id"], "3.1.4", num_plan_phases=1)
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    add_criterion(
        workspace["id"],
        cr_type="unit_test",
        status="accepted",
        details_json=json.dumps({"file": "tests/nonexistent_test.py", "test_names": ["test_foo"]}),
    )

    commit_hash = _make_commit(workspace["working_dir"])

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": commit_hash})
    assert code == 422
    assert "acceptance criteria" in result["message"].lower()


def test_last_commit_passes_with_valid_criteria(workspace, project):
    """Last sub-phase commit passes when all accepted criteria are valid (custom + pre-validated)."""
    _setup_execution_phase(workspace["id"], "3.1.4", num_plan_phases=1)
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    add_criterion(
        workspace["id"],
        cr_type="custom",
        status="accepted",
        details_json=None,
    )
    # Mark the custom criterion as validated (user approved via admin panel)
    db = get_db()
    db.execute(
        "UPDATE acceptance_criteria SET validated = 1 WHERE workspace_id = ?",
        (workspace["id"],)
    )
    db.commit()
    db.close()

    commit_hash = _make_commit(workspace["working_dir"])

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": commit_hash})
    assert code == 200
    assert result["phase"] == "4.0"


def test_last_commit_skips_criteria_when_not_last_subphase(workspace, project):
    """Non-last sub-phase commit skips criteria validation even with invalid criteria."""
    _setup_execution_phase(workspace["id"], "3.1.4", num_plan_phases=3)
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    add_criterion(
        workspace["id"],
        cr_type="unit_test",
        status="accepted",
        details_json=json.dumps({"file": "tests/nonexistent_test.py", "test_names": ["test_foo"]}),
    )

    commit_hash = _make_commit(workspace["working_dir"])

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": commit_hash})
    assert code == 200
    assert result["phase"] == "3.2.0"


# ── Plan approval gate with criteria status ─────────────────────────────────


def test_approve_blocked_by_proposed_criteria(workspace, project):
    """PlanAdvancer at 2.0 blocks when a criterion has 'rejected' status."""
    plan = make_plan_json(1)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved", scope_status="approved")
    add_progress(workspace["id"], "2", "Planning done")
    add_criterion(workspace["id"], status="rejected")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 422
    assert "acceptance criteria" in result["error"].lower()


def test_approve_gate_blocked_by_unresolved_review(client, workspace, project):
    """approve_gate blocked when unresolved review items exist."""
    plan = make_plan_json(2)
    set_phase(workspace["id"], "3.1.3",
              plan_json=plan, plan_status="approved", scope_status="approved")
    add_comment(workspace["id"], scope="review", text="Unresolved finding", resolution="open")
    r = client.post(
        f"/api/ws/{project['id']}/{workspace['branch']}/approve",
        json={}
    )
    assert r.status_code == 422
    data = r.get_json()
    assert "guard_errors" in data


def test_approve_gate_passes_with_resolved_review(client, workspace, project):
    """approve_gate passes when all review items are resolved."""
    from core.db import get_db
    plan = make_plan_json(2)
    set_phase(workspace["id"], "3.1.3",
              plan_json=plan, plan_status="approved", scope_status="approved")
    comment_id = add_comment(workspace["id"], scope="review", text="Resolved finding", resolution="fixed")
    db = get_db()
    db.execute("UPDATE discussions SET status = 'resolved' WHERE id = ?", (comment_id,))
    db.commit()
    db.close()
    r = client.post(
        f"/api/ws/{project['id']}/{workspace['branch']}/approve",
        json={}
    )
    assert r.status_code == 200


# ── Forward-target resolver tests (phase 3.2) ──────────────────────────────────


def _disable_phases(scope_type, scope_id, *phase_ids):
    """Write phase_settings rows disabling the given phase IDs."""
    from services.phase_settings import set_scope_settings
    db = get_db()
    settings = {p: False for p in phase_ids}
    set_scope_settings(db, scope_type, scope_id, settings)
    db.commit()
    db.close()


def _clean_phase_settings():
    db = get_db()
    db.execute("DELETE FROM phase_settings")
    db.commit()
    db.close()


def test_advance_skips_disabled_next_phase(workspace, project):
    """Advance from 1.0 skips disabled 1.1 and lands on 1.2."""
    _disable_phases("device", "", "1.1")
    try:
        set_phase(workspace["id"], "1.0")
        add_progress(workspace["id"], "1.0", "Assessment done")
        add_discussion(workspace["id"], type="research")
        ws = _get_ws_row(workspace["id"])
        result, code = perform_advance(ws, project["path"])
        assert code == 200
        assert result["phase"] == "1.2"
    finally:
        _clean_phase_settings()


def test_advance_through_multiple_disabled(workspace, project):
    """Advance from 1.0 skips 1.1, 1.2, 1.3 and lands on 1.4."""
    _disable_phases("workspace", str(workspace["id"]), "1.1", "1.2", "1.3")
    try:
        set_phase(workspace["id"], "1.0")
        add_progress(workspace["id"], "1.0", "Assessment done")
        add_discussion(workspace["id"], type="research")
        ws = _get_ws_row(workspace["id"])
        result, code = perform_advance(ws, project["path"])
        assert code in (200, 202)
        assert result["phase"] == "1.4"
    finally:
        _clean_phase_settings()


def test_advance_unchanged_when_next_is_enabled(workspace, project):
    """No disabled phases: advance from 1.0 reaches 1.1 as normal."""
    set_phase(workspace["id"], "1.0")
    add_progress(workspace["id"], "1.0", "Assessment done")
    add_discussion(workspace["id"], type="research")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 200
    assert result["phase"] == "1.1"


def test_perform_advance_rejects_templated_phase(workspace, project):
    """A workspace pinned to a template id is a bug — fail loudly instead of crashing."""
    set_phase(workspace["id"], "3.x.0")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"])
    assert code == 400
    assert "error" in result


def test_get_phase_returns_template_for_wildcard_id():
    """``get_phase('3.x.3')`` resolves to a registered template, not a concrete advancer."""
    from advance.phases import get_phase

    template = get_phase("3.x.3")
    assert template is not None
    assert template.id == "3.x.3"
    assert template.is_user_gate is True


def test_get_phase_template_validate_raises():
    """Templates must never be executed directly."""
    import pytest as _pytest

    from advance.phases import get_phase

    template = get_phase("3.x.0")
    with _pytest.raises(NotImplementedError):
        template.validate({}, {}, "")
    with _pytest.raises(NotImplementedError):
        template.next_phase({})


def test_get_phase_concrete_execution_phase_unaffected_by_templates():
    """Concrete ``3.N.K`` still resolves via the factory."""
    from advance.phases import get_phase
    from advance.phases.execution import ImplementationPhase

    concrete = get_phase("3.5.0")
    assert concrete is not None
    assert isinstance(concrete, ImplementationPhase)
    assert concrete.id == "3.5.0"
