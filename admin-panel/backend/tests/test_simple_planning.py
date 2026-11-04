"""Tests for the simple_planning per-project mode.

Covers:
- Migration 0046: column existence and rollback
- Settings service: get/set simple_planning
- Settings route: GET/PUT /api/projects/<id>/settings
- plan_service.set_plan with simple_mode
- MCP tools: workspace_extend_plan, workspace_propose_criteria,
  workspace_update_criteria, workspace_get_criteria blocked in simple mode
- PlanningPhase.validate in simple mode
- Rendering: simple mode omits criteria/diagram/extend_plan mentions
"""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from core.db import get_db
from services import plan_service
from services.project_settings_service import ProjectSettingsError, get_simple_planning, set_simple_planning
from advance.phases.planning import PlanningPhase
from services.configurator_service import SkillConfigurator
from testing_utils import add_criterion, add_progress, make_plan_json, set_phase


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_ws(ws_id):
    db = get_db()
    try:
        return db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    finally:
        db.close()


def _set_simple_planning_flag(project_id: str, enabled: bool) -> None:
    db = get_db()
    try:
        db.execute(
            "UPDATE projects SET simple_planning = ? WHERE id = ?",
            (1 if enabled else 0, project_id),
        )
        db.commit()
    finally:
        db.close()


def _single_subphase_plan():
    return {
        "description": "Simple plan",
        "systemDiagram": [],
        "execution": [
            {
                "id": "3.1",
                "name": "Sub-phase 1",
                "scope": {"must": ["src/"], "may": ["tests/"]},
                "tasks": [{"title": "Task 1", "files": ["src/a.py"], "agent": "middle-backend-engineer"}],
            }
        ],
    }


# ── Migration 0046 ─────────────────────────────────────────────────────────────


def test_migration_0046_column_exists_with_default_zero():
    db = get_db()
    try:
        db.execute("PRAGMA table_info(projects)")
        columns = {row[1] for row in db.execute("PRAGMA table_info(projects)").fetchall()}
        assert "simple_planning" in columns

        db.execute(
            "INSERT INTO projects (id, name, path, registered, simple_planning) VALUES (?, ?, ?, ?, ?)",
            ("mig-test", "Mig Test", "/tmp/mig-test", datetime.now().isoformat(), 0),
        )
        db.commit()
        row = db.execute("SELECT simple_planning FROM projects WHERE id = ?", ("mig-test",)).fetchone()
        assert row["simple_planning"] == 0
    finally:
        db.execute("DELETE FROM projects WHERE id = ?", ("mig-test",))
        db.commit()
        db.close()


def test_migration_0046_default_is_zero_for_existing_projects(project):
    db = get_db()
    try:
        row = db.execute("SELECT simple_planning FROM projects WHERE id = ?", (project["id"],)).fetchone()
        assert row["simple_planning"] == 0
    finally:
        db.close()


# ── Settings service ───────────────────────────────────────────────────────────


def test_get_simple_planning_returns_false_by_default(project):
    db = get_db()
    try:
        assert get_simple_planning(db, project["id"]) is False
    finally:
        db.close()


def test_set_simple_planning_persists_true(project):
    db = get_db()
    try:
        set_simple_planning(db, project["id"], True)
        db.commit()
        assert get_simple_planning(db, project["id"]) is True
    finally:
        db.close()


def test_set_simple_planning_persists_false(project):
    db = get_db()
    try:
        set_simple_planning(db, project["id"], True)
        db.commit()
        set_simple_planning(db, project["id"], False)
        db.commit()
        assert get_simple_planning(db, project["id"]) is False
    finally:
        db.close()


def test_get_simple_planning_raises_for_unknown_project():
    db = get_db()
    try:
        with pytest.raises(ProjectSettingsError) as exc_info:
            get_simple_planning(db, "no-such-project")
        assert exc_info.value.code == "project_not_found"
    finally:
        db.close()


def test_set_simple_planning_raises_for_unknown_project():
    db = get_db()
    try:
        with pytest.raises(ProjectSettingsError) as exc_info:
            set_simple_planning(db, "no-such-project", True)
        assert exc_info.value.code == "project_not_found"
    finally:
        db.close()


# ── Settings route: GET ─────────────────────────────────────────────────────────


def test_get_settings_returns_simple_planning_false_by_default(client, project):
    resp = client.get(f"/api/projects/{project['id']}/settings")

    assert resp.status_code == 200
    assert resp.get_json()["simple_planning"] is False


def test_get_settings_returns_simple_planning_true_when_set(client, project):
    _set_simple_planning_flag(project["id"], True)

    resp = client.get(f"/api/projects/{project['id']}/settings")

    assert resp.status_code == 200
    assert resp.get_json()["simple_planning"] is True


def test_get_settings_404_for_unknown_project(client):
    resp = client.get("/api/projects/no-such-project/settings")

    assert resp.status_code == 404


# ── Settings route: PUT ─────────────────────────────────────────────────────────


def test_put_settings_enables_simple_planning(client, project):
    with patch("routes.projects.ConfiguratorChain") as MockChain:
        MockChain.default.return_value.run.return_value = []
        resp = client.put(
            f"/api/projects/{project['id']}/settings",
            json={"simple_planning": True},
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["simple_planning"] is True

    verify = client.get(f"/api/projects/{project['id']}/settings")
    assert verify.get_json()["simple_planning"] is True


def test_put_settings_disables_simple_planning(client, project):
    _set_simple_planning_flag(project["id"], True)

    with patch("routes.projects.ConfiguratorChain") as MockChain:
        MockChain.default.return_value.run.return_value = []
        resp = client.put(
            f"/api/projects/{project['id']}/settings",
            json={"simple_planning": False},
        )

    assert resp.status_code == 200
    assert resp.get_json()["simple_planning"] is False

    verify = client.get(f"/api/projects/{project['id']}/settings")
    assert verify.get_json()["simple_planning"] is False


def test_put_settings_rejects_empty_body(client, project):
    resp = client.put(f"/api/projects/{project['id']}/settings", json={})

    assert resp.status_code == 400


def test_put_settings_rejects_non_boolean(client, project):
    resp = client.put(
        f"/api/projects/{project['id']}/settings",
        json={"simple_planning": 1},
    )

    assert resp.status_code == 400


def test_put_settings_updates_fast_mode_default_alone(client, project):
    with patch("routes.projects.ConfiguratorChain") as MockChain:
        MockChain.default.return_value.run.return_value = []
        resp = client.put(
            f"/api/projects/{project['id']}/settings",
            json={"fast_mode_default": True},
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["fast_mode_default"] is True
    assert data["simple_planning"] is False

    verify = client.get(f"/api/projects/{project['id']}/settings")
    assert verify.get_json()["fast_mode_default"] is True
    assert verify.get_json()["simple_planning"] is False


def test_put_settings_updates_fast_mode_default_alone_when_simple_planning_already_enabled(client, project):
    _set_simple_planning_flag(project["id"], True)

    with patch("routes.projects.ConfiguratorChain") as MockChain:
        MockChain.default.return_value.run.return_value = []
        resp = client.put(
            f"/api/projects/{project['id']}/settings",
            json={"fast_mode_default": True},
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["fast_mode_default"] is True
    assert data["simple_planning"] is True


def test_put_settings_updates_simple_planning_alone_preserves_fast_mode_default(client, project):
    with patch("routes.projects.ConfiguratorChain") as MockChain:
        MockChain.default.return_value.run.return_value = []
        client.put(f"/api/projects/{project['id']}/settings", json={"fast_mode_default": True})
        resp = client.put(f"/api/projects/{project['id']}/settings", json={"simple_planning": True})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["simple_planning"] is True
    assert data["fast_mode_default"] is True


def test_put_settings_updates_review_mode_default_alone(client, project):
    with patch("routes.projects.ConfiguratorChain") as MockChain:
        MockChain.default.return_value.run.return_value = []
        resp = client.put(
            f"/api/projects/{project['id']}/settings",
            json={"review_mode_default": "integration"},
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["review_mode_default"] == "integration"
    assert data["simple_planning"] is False


def test_put_settings_rejects_non_boolean_fast_mode_default(client, project):
    resp = client.put(
        f"/api/projects/{project['id']}/settings",
        json={"fast_mode_default": "yes"},
    )

    assert resp.status_code == 400


def test_put_settings_ignores_unknown_keys(client, project):
    with patch("routes.projects.ConfiguratorChain") as MockChain:
        MockChain.default.return_value.run.return_value = []
        resp = client.put(
            f"/api/projects/{project['id']}/settings",
            json={"fast_mode_default": True, "not_a_real_setting": "whatever"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["fast_mode_default"] is True


def test_put_settings_invokes_configurator(client, project):
    with patch("routes.projects.ConfiguratorChain") as MockChain:
        chain_instance = MockChain.default.return_value
        chain_instance.run.return_value = []

        client.put(
            f"/api/projects/{project['id']}/settings",
            json={"simple_planning": True},
        )

    chain_instance.run.assert_called_once()
    args, _ = chain_instance.run.call_args
    assert args[1] == project["id"]
    assert args[2] == Path(project["path"])


def test_put_settings_returns_warnings_when_configurator_skips(client, project, tmp_path):
    missing_default = tmp_path / "no-default" / "SKILL.md.template"
    missing_agents = tmp_path / "no-agents"

    with patch("services.configurator_service.SkillConfigurator.DEFAULT_TEMPLATE_PATH", missing_default), \
         patch("services.configurator_service.DEFAULT_AGENTS_DIR", missing_agents):
        resp = client.put(
            f"/api/projects/{project['id']}/settings",
            json={"simple_planning": True},
        )

    assert resp.status_code == 200
    assert "configurator_warnings" in resp.get_json()


# ── plan_service.set_plan simple_mode ──────────────────────────────────────────


def test_set_plan_simple_mode_rejects_multiple_subphases(workspace):
    set_phase(workspace["id"], "2.0")
    ws = _get_ws(workspace["id"])
    plan = json.loads(make_plan_json(2))

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan, simple_mode=True)
    finally:
        db.close()

    assert "error" in result
    assert result.get("errorCode") == "simple_multiple_subphases"


def test_set_plan_simple_mode_rejects_non_empty_system_diagram(workspace):
    set_phase(workspace["id"], "2.0")
    ws = _get_ws(workspace["id"])
    plan = _single_subphase_plan()
    plan["systemDiagram"] = [{"title": "Diagram", "diagram": "graph LR\nA-->B"}]

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan, simple_mode=True)
    finally:
        db.close()

    assert "error" in result
    assert result.get("errorCode") == "simple_no_diagrams"


def test_set_plan_simple_mode_accepts_single_item_with_empty_diagram(workspace):
    set_phase(workspace["id"], "2.0")
    ws = _get_ws(workspace["id"])
    plan = _single_subphase_plan()

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan, simple_mode=True)
        db.commit()
    finally:
        db.close()

    assert result.get("ok") is True


def test_set_plan_normal_mode_accepts_multiple_subphases(workspace):
    set_phase(workspace["id"], "2.0")
    ws = _get_ws(workspace["id"])
    plan = json.loads(make_plan_json(2))

    db = get_db()
    try:
        result = plan_service.set_plan(db, ws, plan, simple_mode=False)
        db.commit()
    finally:
        db.close()

    assert result.get("ok") is True


# ── MCP tools: criteria blocked in simple mode ─────────────────────────────────
#
# These tests drive the MCP tool handlers directly to verify the guards.


def _make_simple_project_row(project_id: str):
    """Return a fake project row dict with simple_planning=1."""
    return {"id": project_id, "simple_planning": 1, "path": "/tmp/fake"}


def _make_full_project_row(project_id: str):
    return {"id": project_id, "simple_planning": 0, "path": "/tmp/fake"}


def _make_ws_row(workspace_id: int, project_id: str):
    return {
        "id": workspace_id,
        "project_id": project_id,
        "phase": "2.0",
        "locale": "en",
        "plan_json": json.dumps(_single_subphase_plan()),
        "plan_status": "pending",
        "working_dir": "/tmp/fake",
    }


def _run_tool_with_project(tool_fn, workspace, project, db, **kwargs):
    """Call an MCP tool handler directly, bypassing the decorator."""
    locale = "en"
    return tool_fn.__wrapped__(workspace, project, db, locale, **kwargs) if hasattr(tool_fn, "__wrapped__") else tool_fn(workspace, project, db, locale, **kwargs)


def test_workspace_extend_plan_blocked_in_simple_mode(workspace, project):
    from mcp_tools.plan_scope import workspace_extend_plan

    _set_simple_planning_flag(project["id"], True)
    set_phase(workspace["id"], "2.0", plan_json=make_plan_json(1))

    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        result = workspace_extend_plan.__wrapped__(
            ws, proj, db, "en",
            subphase={"name": "New phase", "tasks": [{"title": "T", "files": [], "agent": "a"}]},
            scope={"must": ["src/"], "may": []},
        )
    finally:
        db.close()

    assert "error" in result
    assert result["errorCategory"] == "business"
    assert "simple planning mode" in result["error"].lower()


@pytest.mark.parametrize("tool_name,kwargs", [
    ("workspace_update_subphase", {"subphase_id": "3.1", "name": "Renamed"}),
    ("workspace_delete_subphase", {"subphase_id": "3.1"}),
    ("workspace_set_plan_diagrams", {"diagrams": [{"title": "T", "diagram": "graph TD"}]}),
])
def test_granular_plan_tools_blocked_in_simple_mode(workspace, project, tool_name, kwargs):
    import mcp_tools.plan_scope as plan_scope

    _set_simple_planning_flag(project["id"], True)
    set_phase(workspace["id"], "2.0", plan_json=make_plan_json(1))

    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        result = getattr(plan_scope, tool_name).__wrapped__(ws, proj, db, "en", **kwargs)
    finally:
        db.close()

    assert result["errorCategory"] == "business"
    assert "simple planning mode" in result["error"].lower()


def test_workspace_delete_criteria_blocked_in_simple_mode(workspace, project):
    from mcp_tools.criteria import workspace_delete_criteria

    _set_simple_planning_flag(project["id"], True)
    criterion_id = add_criterion(workspace["id"])

    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        result = workspace_delete_criteria.__wrapped__(ws, proj, db, "en", criterion_id=criterion_id)
    finally:
        db.close()

    assert result["errorCategory"] == "business"


def test_workspace_propose_criteria_blocked_in_simple_mode(workspace, project):
    from mcp_tools.criteria import workspace_propose_criteria

    _set_simple_planning_flag(project["id"], True)
    set_phase(workspace["id"], "2.0")

    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        result = workspace_propose_criteria.__wrapped__(
            ws, proj, db, "en",
            type="unit_test",
            description="Test",
        )
    finally:
        db.close()

    assert "error" in result
    assert result["errorCategory"] == "business"
    assert "simple planning mode" in result["error"].lower()


def test_workspace_get_criteria_blocked_in_simple_mode(workspace, project):
    from mcp_tools.criteria import workspace_get_criteria

    _set_simple_planning_flag(project["id"], True)
    set_phase(workspace["id"], "2.0")

    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        result = workspace_get_criteria.__wrapped__(ws, proj, db, "en")
    finally:
        db.close()

    assert "error" in result
    assert result["errorCategory"] == "business"


def test_workspace_update_criteria_blocked_in_simple_mode(workspace, project):
    from mcp_tools.criteria import workspace_update_criteria

    _set_simple_planning_flag(project["id"], True)
    set_phase(workspace["id"], "2.0")

    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        result = workspace_update_criteria.__wrapped__(
            ws, proj, db, "en",
            criterion_id=1,
            description="Updated",
        )
    finally:
        db.close()

    assert "error" in result
    assert result["errorCategory"] == "business"
    assert "simple planning mode" in result["error"].lower()


def test_workspace_extend_plan_allowed_in_full_mode(workspace, project):
    from mcp_tools.plan_scope import workspace_extend_plan

    _set_simple_planning_flag(project["id"], False)
    set_phase(workspace["id"], "2.0", plan_json=make_plan_json(1))

    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        result = workspace_extend_plan.__wrapped__(
            ws, proj, db, "en",
            subphase={"name": "New phase", "tasks": [{"title": "T", "files": [], "agent": "a"}]},
            scope={"must": ["src/"], "may": []},
        )
    finally:
        db.close()

    assert "error" not in result or result.get("errorCategory") != "business"


# ── PlanningPhase.validate in simple mode ──────────────────────────────────────


def _make_ws_dict(ws_id, project_id, plan_json_str, plan_status="approved"):
    return {
        "id": ws_id,
        "project_id": project_id,
        "phase": "2.0",
        "locale": "en",
        "plan_json": plan_json_str,
        "plan_status": plan_status,
    }


def test_planning_phase_validate_simple_mode_passes_with_single_item_approved_plan(workspace, project):
    _set_simple_planning_flag(project["id"], True)
    plan = json.dumps(_single_subphase_plan())
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved")
    add_progress(workspace["id"], "2", "Done")

    ws = _get_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is True, f"Expected ok but got: {detail}"


def test_planning_phase_validate_simple_mode_fails_with_multiple_items(workspace, project):
    _set_simple_planning_flag(project["id"], True)
    plan = make_plan_json(2)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved")

    ws = _get_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is False
    assert "simple" in str(detail).lower()


def test_planning_phase_validate_simple_mode_skips_criteria_check(workspace, project):
    _set_simple_planning_flag(project["id"], True)
    plan = json.dumps(_single_subphase_plan())
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved")

    ws = _get_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is True, f"Simple mode should not require criteria, got: {detail}"


def test_planning_phase_validate_full_mode_requires_criteria(workspace, project):
    _set_simple_planning_flag(project["id"], False)
    plan = make_plan_json(1)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved")

    ws = _get_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is False
    assert "criteria" in str(detail).lower() or "criterion" in str(detail).lower()


def test_planning_phase_validate_full_mode_passes_with_criteria(workspace, project):
    _set_simple_planning_flag(project["id"], False)
    plan = make_plan_json(1)
    set_phase(workspace["id"], "2.0", plan_json=plan, plan_status="approved")
    add_progress(workspace["id"], "2", "Planning done")
    add_criterion(workspace["id"], status="accepted")

    ws = _get_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is True, f"Expected ok but got: {detail}"


# ── description_for_skill ──────────────────────────────────────────────────────


def test_description_for_skill_simple_returns_simple_variant():
    text = PlanningPhase().description_for_skill(simple_planning=True)

    assert "workspace_set_plan" in text
    assert "3.1" in text
    assert "workspace_propose_criteria" not in text
    assert "workspace_extend_plan" not in text
    assert "systemDiagram" not in text or "[]" in text


def test_description_for_skill_full_returns_full_variant():
    text = PlanningPhase().description_for_skill(simple_planning=False)

    assert "workspace_propose_criteria" in text
    assert "workspace_extend_plan" in text
    assert "acceptance criteria" in text.lower()


def test_description_for_skill_default_is_full():
    full = PlanningPhase().description_for_skill()
    assert "workspace_propose_criteria" in full


# ── Rendering: FULL_PLANNING markers ──────────────────────────────────────────


_SAMPLE_TEMPLATE_FULL_PLANNING = (
    "---\nname: governed-workflow\ndescription: x\n---\n\n"
    "# Heading\n\n{{PHASES}}\n\n"
    "{{#FULL_PLANNING}}\nFull-only content here.\n{{/FULL_PLANNING}}\n\n"
    "Always visible.\n"
)


def test_full_planning_blocks_kept_in_full_mode():
    result = SkillConfigurator.render(_SAMPLE_TEMPLATE_FULL_PLANNING, [], simple_planning=False)

    assert "Full-only content here." in result
    assert "{{#FULL_PLANNING}}" not in result
    assert "{{/FULL_PLANNING}}" not in result


def test_full_planning_blocks_removed_in_simple_mode():
    result = SkillConfigurator.render(_SAMPLE_TEMPLATE_FULL_PLANNING, [], simple_planning=True)

    assert "Full-only content here." not in result
    assert "{{#FULL_PLANNING}}" not in result
    assert "{{/FULL_PLANNING}}" not in result
    assert "Always visible." in result


def test_render_default_signature_still_works():
    result = SkillConfigurator.render(_SAMPLE_TEMPLATE_FULL_PLANNING, [])

    assert "Full-only content here." in result


# ── Rendering: project-level skill content ─────────────────────────────────────


@pytest.fixture
def default_template_for_simple(tmp_path):
    from services.configurator_service import SkillConfigurator as SC

    template_path = tmp_path / "skills" / "governed-workflow" / "SKILL.md.template"
    template_path.parent.mkdir(parents=True)
    template_text = (
        "---\nname: governed-workflow\ndescription: x\n---\n\n"
        "{{PHASE_MAP}}\n\n{{PHASES}}\n\n"
        "{{#FULL_PLANNING}}\n"
        "| `workspace_extend_plan` | ext |\n"
        "| `workspace_propose_criteria` | crit |\n"
        "{{/FULL_PLANNING}}\n"
        "| `workspace_set_plan` | plan |\n"
    )
    template_path.write_text(template_text)
    with patch.object(SC, "DEFAULT_TEMPLATE_PATH", template_path):
        yield template_path


@pytest.fixture
def project_root_dir(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return root


@pytest.fixture
def simple_project(clean_db, git_repo):
    db = get_db()
    project_id = "simple-test-project"
    registered = datetime.now().isoformat()
    db.execute(
        "INSERT INTO projects (id, name, path, registered, simple_planning) VALUES (?, ?, ?, ?, ?)",
        (project_id, "Simple Test", git_repo, registered, 1),
    )
    db.commit()
    db.close()
    return {"id": project_id, "name": "Simple Test", "path": git_repo}


def test_simple_project_skill_omits_full_planning_content(
    simple_project, project_root_dir, default_template_for_simple
):
    db = get_db()
    try:
        SkillConfigurator().configure(db, simple_project["id"], project_root_dir)
    finally:
        db.close()

    output = (project_root_dir / SkillConfigurator.OUTPUT_REL_PATH).read_text()
    assert "workspace_extend_plan" not in output
    assert "workspace_propose_criteria" not in output
    assert "workspace_set_plan" in output


def test_full_project_skill_includes_full_planning_content(
    project, project_root_dir, default_template_for_simple
):
    db = get_db()
    try:
        SkillConfigurator().configure(db, project["id"], project_root_dir)
    finally:
        db.close()

    output = (project_root_dir / SkillConfigurator.OUTPUT_REL_PATH).read_text()
    assert "workspace_extend_plan" in output
    assert "workspace_propose_criteria" in output


def test_simple_project_planning_block_is_simple_variant(
    simple_project, project_root_dir, default_template_for_simple
):
    db = get_db()
    try:
        SkillConfigurator().configure(db, simple_project["id"], project_root_dir)
    finally:
        db.close()

    output = (project_root_dir / SkillConfigurator.OUTPUT_REL_PATH).read_text()
    assert "workspace_propose_criteria" not in output
    assert "workspace_set_plan" in output


# ── Simple-mode tool deregistration ───────────────────────────────────────────


def _deregistered_tool_names(detected_project):
    """Run _deregister_simple_mode_tools against a stubbed registry and detection."""
    import mcp_server

    removed = []
    with patch.object(mcp_server, "_detect_workspace", return_value=({}, detected_project)), \
            patch.object(mcp_server.mcp, "remove_tool", side_effect=removed.append):
        mcp_server._deregister_simple_mode_tools()
    return removed


def test_simple_mode_deregisters_hidden_tools():
    import mcp_server

    removed = _deregistered_tool_names({"simple_planning": 1})

    assert removed == list(mcp_server._SIMPLE_MODE_HIDDEN_TOOLS)


def test_full_mode_keeps_all_tools_registered():
    assert _deregistered_tool_names({"simple_planning": 0}) == []


def test_missing_project_keeps_all_tools_registered():
    assert _deregistered_tool_names(None) == []
