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


# ── granular plan edits ─────────────────────────────────────────────────────────


def _plan_status_of(ws_id):
    db = get_db()
    try:
        return db.execute("SELECT plan_status FROM workspaces WHERE id = ?", (ws_id,)).fetchone()["plan_status"]
    finally:
        db.close()


def _plan_of(ws_id):
    return json.loads(_ws_row(ws_id)["plan_json"])


def _call_committed(ws_id, operation, *args, **kwargs):
    """Run a plan_service operation against a fresh ws row and commit it."""
    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
        result = operation(db, ws, *args, **kwargs)
        db.commit()
        return result
    finally:
        db.close()


def _seed_approved_plan(ws_id, num_phases=3, phase="2.0"):
    set_phase(ws_id, phase, plan_json=make_plan_json(num_phases), plan_status="approved")


def test_update_subphase_patches_only_supplied_fields(workspace):
    _seed_approved_plan(workspace["id"])

    result = _call_committed(workspace["id"], plan_service.update_subphase, "3.2", name="Renamed")

    assert result["ok"] is True
    items = _plan_of(workspace["id"])["execution"]
    assert items[1]["name"] == "Renamed"
    assert items[1]["scope"] == {"must": ["src/"], "may": ["tests/"]}
    assert items[1]["tasks"] == [{"title": "Task 2", "files": ["src/phase2/file.py"],
                                 "agent": "middle-backend-engineer"}]
    assert items[0]["name"] == "Sub-phase 1"
    assert items[2]["id"] == "3.3"


def test_update_subphase_replaces_tasks_and_scope(workspace):
    _seed_approved_plan(workspace["id"], num_phases=2)
    new_tasks = [{"title": "New", "files": ["src/x.py"], "agent": "middle-backend-engineer"}]

    result = _call_committed(
        workspace["id"], plan_service.update_subphase, "3.1",
        tasks=new_tasks, scope={"must": ["src/x.py"]},
    )

    assert result["ok"] is True
    item = _plan_of(workspace["id"])["execution"][0]
    assert item["tasks"] == new_tasks
    assert item["scope"] == {"must": ["src/x.py"]}
    assert item["name"] == "Sub-phase 1"


def test_update_subphase_revokes_approval(workspace):
    _seed_approved_plan(workspace["id"], num_phases=2)

    _call_committed(workspace["id"], plan_service.update_subphase, "3.1", name="Renamed")

    assert _plan_status_of(workspace["id"]) == "pending"


def test_update_subphase_unknown_id_returns_not_found_code(workspace):
    _seed_approved_plan(workspace["id"], num_phases=2)

    result = _call_committed(workspace["id"], plan_service.update_subphase, "3.9", name="Nope")

    assert result["errorCode"] == "subphase_not_found"
    assert _plan_status_of(workspace["id"]) == "approved"


def test_update_subphase_without_any_field_is_rejected(workspace):
    _seed_approved_plan(workspace["id"], num_phases=2)

    result = _call_committed(workspace["id"], plan_service.update_subphase, "3.1")

    assert result["errorCode"] == "nothing_to_update"


def test_update_subphase_rejects_blank_name_and_bad_tasks(workspace):
    _seed_approved_plan(workspace["id"], num_phases=2)

    blank_name = _call_committed(workspace["id"], plan_service.update_subphase, "3.1", name="   ")
    bad_tasks = _call_committed(
        workspace["id"], plan_service.update_subphase, "3.1",
        tasks=[{"title": "no files", "agent": "a"}],
    )
    bad_scope = _call_committed(
        workspace["id"], plan_service.update_subphase, "3.1", scope={"may": ["x"]},
    )

    assert "name" in blank_name["error"]
    assert "task[0]" in bad_tasks["error"]
    assert "must" in bad_scope["error"]


def test_update_subphase_rejected_before_planning_phase(workspace):
    set_phase(workspace["id"], "1.0", plan_json=make_plan_json(2))

    result = _call_committed(workspace["id"], plan_service.update_subphase, "3.1", name="Nope")

    assert "error" in result
    assert "ok" not in result


def test_delete_subphase_renumbers_remaining_items_in_order(workspace):
    _seed_approved_plan(workspace["id"])

    result = _call_committed(workspace["id"], plan_service.delete_subphase, "3.1")

    assert result["ok"] is True
    assert result["execution_ids"] == ["3.1", "3.2"]
    items = _plan_of(workspace["id"])["execution"]
    assert [item["name"] for item in items] == ["Sub-phase 2", "Sub-phase 3"]
    assert items[0]["tasks"][0]["title"] == "Task 2"
    assert items[1]["tasks"][0]["title"] == "Task 3"


def test_delete_subphase_revokes_approval(workspace):
    _seed_approved_plan(workspace["id"])

    _call_committed(workspace["id"], plan_service.delete_subphase, "3.3")

    assert _plan_status_of(workspace["id"]) == "pending"


def test_delete_subphase_rewinds_phase_when_current_item_drops_off(workspace):
    _seed_approved_plan(workspace["id"], num_phases=3, phase="3.3.0")

    result = _call_committed(workspace["id"], plan_service.delete_subphase, "3.1")

    assert result["phase"] == "2.0"
    assert _phase_of(workspace["id"]) == "2.0"
    assert get_phase("2.0") is not None


def test_delete_subphase_keeps_phase_when_current_item_survives(workspace):
    _seed_approved_plan(workspace["id"], num_phases=3, phase="3.1.0")

    result = _call_committed(workspace["id"], plan_service.delete_subphase, "3.3")

    assert result["phase"] == "3.1.0"
    assert _phase_of(workspace["id"]) == "3.1.0"


def test_delete_subphase_refuses_last_remaining_item(workspace):
    _seed_approved_plan(workspace["id"], num_phases=1)

    result = _call_committed(workspace["id"], plan_service.delete_subphase, "3.1")

    assert result["errorCode"] == "cannot_delete_last_subphase"
    assert len(_plan_of(workspace["id"])["execution"]) == 1
    assert _plan_status_of(workspace["id"]) == "approved"


def test_delete_subphase_unknown_id_returns_not_found_code(workspace):
    _seed_approved_plan(workspace["id"], num_phases=2)

    result = _call_committed(workspace["id"], plan_service.delete_subphase, "3.7")

    assert result["errorCode"] == "subphase_not_found"


def test_delete_subphase_rejected_before_planning_phase(workspace):
    set_phase(workspace["id"], "1.0", plan_json=make_plan_json(2))

    result = _call_committed(workspace["id"], plan_service.delete_subphase, "3.1")

    assert "ok" not in result


def test_set_diagrams_replaces_by_default_and_keeps_approval(workspace):
    _seed_approved_plan(workspace["id"], num_phases=1)
    diagrams = [{"title": "Class Diagram", "diagram": "classDiagram\n  A --> B"}]

    result = _call_committed(workspace["id"], plan_service.set_diagrams, diagrams)

    assert result == {"ok": True, "diagram_count": 1}
    assert _plan_of(workspace["id"])["systemDiagram"] == diagrams
    assert _plan_status_of(workspace["id"]) == "approved"


def test_set_diagrams_appends_to_existing_entries(workspace):
    _seed_approved_plan(workspace["id"], num_phases=1)
    first = [{"title": "Class Diagram", "diagram": "classDiagram\n  A --> B"}]
    second = [{"title": "Auth Flow", "diagram": "sequenceDiagram\n  A ->> B: hi"}]

    _call_committed(workspace["id"], plan_service.set_diagrams, first)
    result = _call_committed(workspace["id"], plan_service.set_diagrams, second, replace=False)

    assert result["diagram_count"] == 2
    assert [d["title"] for d in _plan_of(workspace["id"])["systemDiagram"]] == ["Class Diagram", "Auth Flow"]


def test_set_diagrams_append_coerces_legacy_string_diagram(workspace):
    _seed_approved_plan(workspace["id"], num_phases=1)

    result = _call_committed(
        workspace["id"], plan_service.set_diagrams,
        [{"title": "New", "diagram": "graph TD"}], replace=False,
    )

    diagrams = _plan_of(workspace["id"])["systemDiagram"]
    assert result["diagram_count"] == 2
    assert diagrams[0] == {"title": "", "diagram": "graph LR"}
    assert diagrams[1]["title"] == "New"


def test_set_diagrams_rejects_malformed_entries(workspace):
    _seed_approved_plan(workspace["id"], num_phases=1)

    not_a_list = _call_committed(workspace["id"], plan_service.set_diagrams, "graph LR")
    not_objects = _call_committed(workspace["id"], plan_service.set_diagrams, ["graph LR"])
    blank_title = _call_committed(
        workspace["id"], plan_service.set_diagrams, [{"title": " ", "diagram": "graph LR"}])
    missing_body = _call_committed(
        workspace["id"], plan_service.set_diagrams, [{"title": "T"}])
    empty_append = _call_committed(
        workspace["id"], plan_service.set_diagrams, [], replace=False)

    for result in (not_a_list, not_objects, blank_title, missing_body, empty_append):
        assert "error" in result
        assert "ok" not in result
    assert _plan_of(workspace["id"])["systemDiagram"] == "graph LR"


def test_set_diagrams_replace_with_empty_list_clears_diagrams(workspace):
    _seed_approved_plan(workspace["id"], num_phases=1)

    result = _call_committed(workspace["id"], plan_service.set_diagrams, [])

    assert result["diagram_count"] == 0
    assert _plan_of(workspace["id"])["systemDiagram"] == []


def test_set_diagrams_rejected_before_planning_phase(workspace):
    set_phase(workspace["id"], "1.0", plan_json=make_plan_json(1))

    result = _call_committed(
        workspace["id"], plan_service.set_diagrams, [{"title": "T", "diagram": "graph LR"}])

    assert "ok" not in result


def test_set_description_replaces_text_and_keeps_approval(workspace):
    _seed_approved_plan(workspace["id"], num_phases=2)

    result = _call_committed(workspace["id"], plan_service.set_description, "  Reworded plan  ")

    assert result == {"ok": True, "description": "Reworded plan"}
    plan = _plan_of(workspace["id"])
    assert plan["description"] == "Reworded plan"
    assert len(plan["execution"]) == 2
    assert _plan_status_of(workspace["id"]) == "approved"


def test_set_description_rejects_blank_text(workspace):
    _seed_approved_plan(workspace["id"], num_phases=1)

    result = _call_committed(workspace["id"], plan_service.set_description, "   ")

    assert "error" in result
    assert _plan_of(workspace["id"])["description"] == "Test plan description"


def test_set_description_rejected_before_planning_phase(workspace):
    set_phase(workspace["id"], "1.0", plan_json=make_plan_json(1))

    result = _call_committed(workspace["id"], plan_service.set_description, "New text")

    assert "ok" not in result
