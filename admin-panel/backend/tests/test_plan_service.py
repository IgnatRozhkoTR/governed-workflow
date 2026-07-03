"""Tests for plan_service set_plan / extend_plan phase adjustment and embedded scope."""
import json

from advance.phases import get_phase
from core.db import get_db
from services import plan_service
from services import scope_service
from testing_utils import make_plan_json, set_phase


def _ws_row(ws_id):
    db = get_db()
    try:
        return db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    finally:
        db.close()


def _phase_of(ws_id):
    db = get_db()
    try:
        return db.execute("SELECT phase FROM workspaces WHERE id = ?", (ws_id,)).fetchone()["phase"]
    finally:
        db.close()


def _set_plan_committed(ws, plan_data):
    """Call set_plan and commit on the same connection (callers own the commit)."""
    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan_data)
        db.commit()
        return result
    finally:
        db.close()


def test_set_plan_resets_to_replanning_when_plan_shrinks_below_current_item(workspace):
    """A re-plan that drops the current 3.N item must land on a registered phase, not '3.0'."""
    set_phase(workspace["id"], "3.3.0", plan_json=make_plan_json(3), plan_status="approved")
    ws = _ws_row(workspace["id"])

    result = _set_plan_committed(ws, json.loads(make_plan_json(1)))

    assert result["ok"] is True
    new_phase = _phase_of(workspace["id"])
    assert new_phase == "2.0"
    assert get_phase(new_phase) is not None


def test_set_plan_resets_to_replanning_when_execution_empty(workspace):
    """Clearing the execution list resets to 2.0 (re-planning)."""
    set_phase(workspace["id"], "3.2.0", plan_json=make_plan_json(2), plan_status="approved")
    ws = _ws_row(workspace["id"])

    empty_plan = {"description": "", "systemDiagram": "", "execution": []}
    result = _set_plan_committed(ws, empty_plan)

    assert result["ok"] is True
    assert _phase_of(workspace["id"]) == "2.0"


def test_set_plan_keeps_phase_when_current_item_still_in_plan(workspace):
    """A re-plan that keeps the current 3.N item leaves the phase untouched."""
    set_phase(workspace["id"], "3.1.0", plan_json=make_plan_json(3), plan_status="approved")
    ws = _ws_row(workspace["id"])

    result = _set_plan_committed(ws, json.loads(make_plan_json(2)))

    assert result["ok"] is True
    assert _phase_of(workspace["id"]) == "3.1.0"


def test_set_plan_requires_per_item_scope(workspace):
    """set_plan rejects an execution item that has no scope.must list."""
    set_phase(workspace["id"], "2.0")
    ws = _ws_row(workspace["id"])

    plan_without_scope = {
        "description": "", "systemDiagram": "",
        "execution": [{"id": "3.1", "name": "P1", "tasks": []}],
    }
    result = _set_plan_committed(ws, plan_without_scope)

    assert "error" in result
    assert "scope" in result["error"].lower()


def test_get_scope_reconstructs_phase_keyed_map_from_plan(workspace):
    """get_scope rebuilds {3.N: {must, may}} from the plan execution items."""
    plan = {
        "description": "", "systemDiagram": "",
        "execution": [
            {"id": "3.1", "name": "P1", "scope": {"must": ["src/a/"], "may": []}, "tasks": []},
            {"id": "3.2", "name": "P2", "scope": {"must": ["src/b/"], "may": ["t/"]}, "tasks": []},
        ],
    }
    set_phase(workspace["id"], "2.0", plan_json=json.dumps(plan))
    ws = _ws_row(workspace["id"])

    scope_map = plan_service.get_scope(ws)

    assert scope_map == {
        "3.1": {"must": ["src/a/"], "may": []},
        "3.2": {"must": ["src/b/"], "may": ["t/"]},
    }


def test_scope_accessors_read_must_patterns_for_subphase(workspace):
    """get_phase_must_patterns resolves the active 3.N sub-key from the plan scope."""
    plan = {
        "description": "", "systemDiagram": "",
        "execution": [
            {"id": "3.1", "name": "P1", "scope": {"must": ["src/a/"], "may": []}, "tasks": []},
            {"id": "3.2", "name": "P2", "scope": {"must": ["src/b/"], "may": ["t/"]}, "tasks": []},
        ],
    }
    set_phase(workspace["id"], "3.2.0", plan_json=json.dumps(plan))
    ws = _ws_row(workspace["id"])

    scope_map = plan_service.get_scope(ws)
    must = scope_service.get_phase_must_patterns(scope_map, "3.2.0")
    must_combined, may_combined = scope_service.get_scope_patterns(scope_map, "3.2.0")

    assert must == ["src/b/"]
    assert must_combined == ["src/b/"]
    assert may_combined == ["t/"]
    assert scope_service.match_scope_patterns("src/b/file.py", scope_map, "3.2.0") is True
    assert scope_service.match_scope_patterns("src/a/file.py", scope_map, "3.2.0") is False


# ── set_plan fast_mode ──────────────────────────────────────────────────────────


def test_exceeds_single_execution_item_true_for_multiple():
    assert plan_service.exceeds_single_execution_item(json.loads(make_plan_json(2))["execution"]) is True


def test_exceeds_single_execution_item_false_for_one():
    assert plan_service.exceeds_single_execution_item(json.loads(make_plan_json(1))["execution"]) is False


def test_set_plan_fast_mode_rejects_multiple_subphases(workspace):
    set_phase(workspace["id"], "2.0")
    ws = _ws_row(workspace["id"])
    plan = json.loads(make_plan_json(2))

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan, fast_mode=True)
    finally:
        db.close()

    assert "error" in result
    assert result.get("errorCode") == "fast_multiple_subphases"


def test_set_plan_fast_mode_accepts_single_subphase(workspace):
    set_phase(workspace["id"], "2.0")
    ws = _ws_row(workspace["id"])
    plan = json.loads(make_plan_json(1))

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan, fast_mode=True)
        db.commit()
    finally:
        db.close()

    assert result.get("ok") is True


def test_set_plan_fast_mode_allows_system_diagram(workspace):
    """Unlike simple_mode, fast_mode does not restrict system diagrams."""
    set_phase(workspace["id"], "2.0")
    ws = _ws_row(workspace["id"])
    plan = json.loads(make_plan_json(1))
    plan["systemDiagram"] = [{"title": "Diagram", "diagram": "graph LR\nA-->B"}]

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan, fast_mode=True)
        db.commit()
    finally:
        db.close()

    assert result.get("ok") is True


def test_set_plan_simple_mode_takes_precedence_over_fast_mode(workspace):
    """When both flags are set, simple_mode's stricter diagram check still applies."""
    set_phase(workspace["id"], "2.0")
    ws = _ws_row(workspace["id"])
    plan = json.loads(make_plan_json(1))
    plan["systemDiagram"] = [{"title": "Diagram", "diagram": "graph LR\nA-->B"}]

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan, simple_mode=True, fast_mode=True)
    finally:
        db.close()

    assert result.get("errorCode") == "simple_no_diagrams"
