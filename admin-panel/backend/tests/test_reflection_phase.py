"""Tests for ReflectionPhase (5.1) and ManualImplementationPhase (5.2)."""
from datetime import datetime

from advance.phases.finalization import ManualImplementationPhase, ReflectionPhase
from core.db import get_db


# ── Helpers ───────────────────────────────────────────────────────────────────


def _insert_proposal(
    db,
    *,
    workspace_id: int,
    project_id: str,
    implementation_kind: str,
    status: str,
    proposal_type: str = "rule_new",
    title: str = "Test proposal",
) -> int:
    cursor = db.execute(
        "INSERT INTO proposals "
        "(workspace_id, project_id, type, implementation_kind, status, title, body, "
        "payload_json, origin, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            workspace_id,
            project_id,
            proposal_type,
            implementation_kind,
            status,
            title,
            "",
            "{}",
            "reflection",
            datetime.now().isoformat(),
        ),
    )
    db.commit()
    return cursor.lastrowid


def _ws_row(workspace_id: int):
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    finally:
        db.close()


# ── Identity / contract ───────────────────────────────────────────────────────


def test_reflection_phase_id_is_5_1():
    assert ReflectionPhase().id == "5.1"


def test_reflection_phase_name_is_reflection():
    assert ReflectionPhase().name == "Reflection"


def test_reflection_phase_boundary_key_is_5():
    assert ReflectionPhase().boundary_key == "5"


def test_reflection_phase_is_not_user_gate():
    assert ReflectionPhase().is_user_gate is False


# ── validate ──────────────────────────────────────────────────────────────────


def test_reflection_phase_validate_returns_true(workspace):
    ws = _ws_row(workspace["id"])

    ok, details = ReflectionPhase().validate(ws, {}, "/tmp")

    assert ok is True
    assert details == {}


# ── next_phase routing ────────────────────────────────────────────────────────


def test_reflection_phase_next_phase_returns_6_when_no_manual_proposals(workspace):
    ws = _ws_row(workspace["id"])

    target = ReflectionPhase().next_phase(ws)

    assert target == "6"


def test_reflection_phase_next_phase_returns_6_when_only_auto_proposals(workspace, project):
    db = get_db()
    try:
        _insert_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=project["id"],
            implementation_kind="auto",
            status="proposed",
        )
    finally:
        db.close()
    ws = _ws_row(workspace["id"])

    target = ReflectionPhase().next_phase(ws)

    assert target == "6"


def test_reflection_phase_next_phase_returns_6_when_manual_proposal_already_executed(
    workspace, project
):
    db = get_db()
    try:
        _insert_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=project["id"],
            implementation_kind="manual",
            status="executed",
        )
    finally:
        db.close()
    ws = _ws_row(workspace["id"])

    target = ReflectionPhase().next_phase(ws)

    assert target == "6"


def test_reflection_phase_next_phase_returns_5_2_when_unresolved_manual_proposal_exists(
    workspace, project
):
    db = get_db()
    try:
        _insert_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=project["id"],
            implementation_kind="manual",
            status="proposed",
        )
    finally:
        db.close()
    ws = _ws_row(workspace["id"])

    target = ReflectionPhase().next_phase(ws)

    assert target == "5.2"


def test_reflection_phase_next_phase_ignores_manual_proposals_for_other_workspaces(
    workspace, second_workspace, project
):
    """A manual proposal belonging to a different workspace must not route this one to 5.2."""
    db = get_db()
    try:
        _insert_proposal(
            db,
            workspace_id=second_workspace["id"],
            project_id=project["id"],
            implementation_kind="manual",
            status="proposed",
        )
    finally:
        db.close()
    ws = _ws_row(workspace["id"])

    target = ReflectionPhase().next_phase(ws)

    assert target == "6"


# ── description_for_skill ─────────────────────────────────────────────────────


def test_reflection_phase_description_for_skill_mentions_required_mcp_tools():
    description = ReflectionPhase().description_for_skill()

    assert "workspace_get_reflection_context" in description
    assert "workspace_submit_proposal" in description
    assert "workspace_list_proposals" in description


def test_reflection_phase_description_for_skill_starts_with_heading():
    description = ReflectionPhase().description_for_skill()

    assert description.lstrip().startswith("## ")


# ── ManualImplementationPhase ─────────────────────────────────────────────────


def test_manual_implementation_phase_id_is_5_2():
    assert ManualImplementationPhase().id == "5.2"


def test_manual_implementation_phase_name_is_manual_implementation():
    assert ManualImplementationPhase().name == "Manual implementation"


def test_manual_implementation_phase_boundary_key_is_5():
    assert ManualImplementationPhase().boundary_key == "5"


def test_manual_implementation_phase_is_not_user_gate():
    assert ManualImplementationPhase().is_user_gate is False


def test_manual_implementation_phase_validate_returns_true(workspace):
    ws = _ws_row(workspace["id"])

    ok, details = ManualImplementationPhase().validate(ws, {}, "/tmp")

    assert ok is True
    assert details == {}


def test_manual_implementation_phase_next_phase_returns_6(workspace):
    ws = _ws_row(workspace["id"])

    assert ManualImplementationPhase().next_phase(ws) == "6"


def test_manual_implementation_phase_description_mentions_proposal_tools():
    description = ManualImplementationPhase().description_for_skill()

    assert "workspace_list_proposals" in description
    assert "workspace_resolve_proposal" in description
