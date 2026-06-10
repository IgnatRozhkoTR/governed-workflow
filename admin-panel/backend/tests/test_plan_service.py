"""Tests for plan_service set_plan / extend_plan phase adjustment."""
import json

from advance.phases import get_phase
from core.db import get_db
from services import plan_service
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
    set_phase(workspace["id"], "3.3.0", plan_json=make_plan_json(3), plan_status="approved",
              scope_status="approved")
    ws = _ws_row(workspace["id"])

    result = _set_plan_committed(ws, json.loads(make_plan_json(1)))

    assert result["ok"] is True
    new_phase = _phase_of(workspace["id"])
    assert new_phase == "2.0"
    assert get_phase(new_phase) is not None


def test_set_plan_resets_to_replanning_when_execution_empty(workspace):
    """Clearing the execution list resets to 2.0 (re-planning)."""
    set_phase(workspace["id"], "3.2.0", plan_json=make_plan_json(2), plan_status="approved",
              scope_status="approved")
    ws = _ws_row(workspace["id"])

    empty_plan = {"description": "", "systemDiagram": "", "execution": []}
    result = _set_plan_committed(ws, empty_plan)

    assert result["ok"] is True
    assert _phase_of(workspace["id"]) == "2.0"


def test_set_plan_keeps_phase_when_current_item_still_in_plan(workspace):
    """A re-plan that keeps the current 3.N item leaves the phase untouched."""
    set_phase(workspace["id"], "3.1.0", plan_json=make_plan_json(3), plan_status="approved",
              scope_status="approved")
    ws = _ws_row(workspace["id"])

    result = _set_plan_committed(ws, json.loads(make_plan_json(2)))

    assert result["ok"] is True
    assert _phase_of(workspace["id"]) == "3.1.0"
