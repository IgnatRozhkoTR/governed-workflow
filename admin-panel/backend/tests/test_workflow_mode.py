"""Tests for the per-workspace fast/standard workflow mode.

Covers:
- Migration 0048: workspaces.workflow_mode + projects.fast_mode_default columns
- workflow_mode_service: phase-settings writes/removes, column update, validation,
  and creation default resolution
- PUT /api/ws/<project>/<branch>/workflow-mode route
- create_workspace honoring explicit mode and project fast_mode_default
- state GET exposing workflow_mode + enabled_phases
- workspace list GET exposing workflow_mode
- SkillConfigurator rendering different content for fast vs standard worktrees
- PlanningPhase.validate enforcing a single execution item in fast mode
- Rendered SKILL.md content for fast workspaces (integration-reviewer mention,
  absence of disabled-phase markers) vs standard workspaces (unchanged)
"""
from datetime import datetime
from unittest.mock import patch

import pytest

from advance.phases.planning import PlanningPhase
from core.db import get_db
from services import workflow_mode_service
from services.configurator_service import SkillConfigurator
from services.phase_settings import get_scope_settings, set_scope_settings
from testing_utils import add_criterion, add_progress, make_plan_json, set_phase

FAST_ROWS = {"1.3", "1.4", "3.x.1", "3.x.2", "3.x.3", "4.0"}


def _ws_url(project, path):
    return f"/api/ws/{project['id']}/feature/test/{path}"


def _reload_ws(ws_id):
    db = get_db()
    try:
        return db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    finally:
        db.close()


def _reload_project(project_id):
    db = get_db()
    try:
        return db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    finally:
        db.close()


def _insert_workspace(db, project_id, branch, working_dir, workflow_mode):
    cursor = db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch, workflow_mode) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', '{}', 'develop', ?)",
        (project_id, branch, branch.replace("/", "-"), str(working_dir),
         datetime.now().isoformat(), workflow_mode),
    )
    return cursor.lastrowid


# ── Migration 0048 ─────────────────────────────────────────────────────────────


def test_migration_0048_adds_both_columns():
    db = get_db()
    try:
        ws_cols = {r[1] for r in db.execute("PRAGMA table_info(workspaces)").fetchall()}
        proj_cols = {r[1] for r in db.execute("PRAGMA table_info(projects)").fetchall()}
    finally:
        db.close()
    assert "workflow_mode" in ws_cols
    assert "fast_mode_default" in proj_cols


def test_migration_0048_defaults(project, workspace):
    ws = _reload_ws(workspace["id"])
    proj = _reload_project(project["id"])
    assert ws["workflow_mode"] == "standard"
    assert proj["fast_mode_default"] == 0


# ── workflow_mode_service: phase-settings rows ─────────────────────────────────


def test_apply_fast_writes_expected_rows_including_mirror(workspace):
    db = get_db()
    try:
        workflow_mode_service.apply_mode_phase_settings(db, workspace["id"], "fast")
        db.commit()
        rows = get_scope_settings(db, "workspace", str(workspace["id"]))
    finally:
        db.close()
    assert set(rows.keys()) == FAST_ROWS
    assert all(value is False for value in rows.values())


def test_apply_fast_writes_no_reflection_disable_rows(workspace):
    """Fast mode now includes the reflection phases, so 5.1/5.2 must stay enabled."""
    db = get_db()
    try:
        workflow_mode_service.apply_mode_phase_settings(db, workspace["id"], "fast")
        db.commit()
        rows = get_scope_settings(db, "workspace", str(workspace["id"]))
    finally:
        db.close()
    assert "5.1" not in rows
    assert "5.2" not in rows


def test_apply_standard_removes_legacy_reflection_disable_rows(workspace):
    """Reverting to standard must clear legacy 5.1/5.2 rows left by pre-change fast mode."""
    db = get_db()
    try:
        set_scope_settings(db, "workspace", str(workspace["id"]), {"5.1": False, "5.2": False})
        db.commit()
        workflow_mode_service.apply_mode_phase_settings(db, workspace["id"], "standard")
        db.commit()
        rows = get_scope_settings(db, "workspace", str(workspace["id"]))
    finally:
        db.close()
    assert rows == {}


def test_apply_standard_removes_fast_rows(workspace):
    db = get_db()
    try:
        workflow_mode_service.apply_mode_phase_settings(db, workspace["id"], "fast")
        db.commit()
        workflow_mode_service.apply_mode_phase_settings(db, workspace["id"], "standard")
        db.commit()
        rows = get_scope_settings(db, "workspace", str(workspace["id"]))
    finally:
        db.close()
    assert rows == {}


def test_apply_mode_rejects_invalid_mode(workspace):
    db = get_db()
    try:
        with pytest.raises(ValueError):
            workflow_mode_service.apply_mode_phase_settings(db, workspace["id"], "turbo")
    finally:
        db.close()


def test_set_workspace_mode_updates_column_and_rows(workspace, project):
    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        workflow_mode_service.set_workspace_mode(db, proj, ws, "fast")
        db.commit()
    finally:
        db.close()

    reloaded = _reload_ws(workspace["id"])
    assert reloaded["workflow_mode"] == "fast"
    db = get_db()
    try:
        rows = get_scope_settings(db, "workspace", str(workspace["id"]))
    finally:
        db.close()
    assert rows["4.0"] is False


def test_set_workspace_mode_rejects_invalid_mode(workspace, project):
    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        with pytest.raises(ValueError):
            workflow_mode_service.set_workspace_mode(db, proj, ws, "nope")
    finally:
        db.close()


# ── workflow_mode_service: creation default resolution ─────────────────────────


def test_resolve_default_mode_explicit_request_wins():
    assert workflow_mode_service.resolve_default_mode({"fast_mode_default": 1}, "standard") == "standard"


def test_resolve_default_mode_uses_project_fast_default():
    assert workflow_mode_service.resolve_default_mode({"fast_mode_default": 1}) == "fast"


def test_resolve_default_mode_uses_project_standard_default():
    assert workflow_mode_service.resolve_default_mode({"fast_mode_default": 0}) == "standard"


def test_resolve_default_mode_rejects_invalid_explicit():
    with pytest.raises(ValueError):
        workflow_mode_service.resolve_default_mode({"fast_mode_default": 0}, "turbo")


# ── Route: PUT /workflow-mode ──────────────────────────────────────────────────


def test_put_workflow_mode_toggles_both_ways(client, workspace, project):
    fast = client.put(_ws_url(project, "workflow-mode"), json={"mode": "fast"})
    assert fast.status_code == 200
    assert fast.json["mode"] == "fast"
    assert _reload_ws(workspace["id"])["workflow_mode"] == "fast"

    standard = client.put(_ws_url(project, "workflow-mode"), json={"mode": "standard"})
    assert standard.status_code == 200
    assert standard.json["mode"] == "standard"
    assert _reload_ws(workspace["id"])["workflow_mode"] == "standard"


def test_put_workflow_mode_rejects_invalid(client, workspace, project):
    resp = client.put(_ws_url(project, "workflow-mode"), json={"mode": "turbo"})
    assert resp.status_code == 400


def test_put_workflow_mode_unknown_workspace(client, project):
    resp = client.put(
        f"/api/ws/{project['id']}/feature/nonexistent/workflow-mode",
        json={"mode": "fast"},
    )
    assert resp.status_code == 404


# ── create_workspace mode resolution ───────────────────────────────────────────


def _created_ws(project_id, branch):
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM workspaces WHERE project_id = ? AND branch = ?",
            (project_id, branch),
        ).fetchone()
    finally:
        db.close()


def test_create_workspace_honors_explicit_fast_mode(client, project):
    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/explicit-fast", "source": "develop",
              "worktree": True, "workflow_mode": "fast"},
    )
    assert resp.status_code == 201

    ws = _created_ws(project["id"], "feature/explicit-fast")
    assert ws["workflow_mode"] == "fast"
    db = get_db()
    try:
        rows = get_scope_settings(db, "workspace", str(ws["id"]))
    finally:
        db.close()
    assert rows["4.0"] is False


def test_create_workspace_uses_project_fast_default(client, project):
    db = get_db()
    try:
        db.execute("UPDATE projects SET fast_mode_default = 1 WHERE id = ?", (project["id"],))
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/default-fast", "source": "develop", "worktree": True},
    )
    assert resp.status_code == 201
    assert _created_ws(project["id"], "feature/default-fast")["workflow_mode"] == "fast"


def test_create_workspace_defaults_to_standard(client, project):
    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/default-standard", "source": "develop", "worktree": True},
    )
    assert resp.status_code == 201

    ws = _created_ws(project["id"], "feature/default-standard")
    assert ws["workflow_mode"] == "standard"
    db = get_db()
    try:
        rows = get_scope_settings(db, "workspace", str(ws["id"]))
    finally:
        db.close()
    assert rows == {}


def test_create_workspace_rejects_invalid_mode(client, project):
    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/bad-mode", "source": "develop",
              "worktree": True, "workflow_mode": "turbo"},
    )
    assert resp.status_code == 400


# ── state GET exposure ─────────────────────────────────────────────────────────


def test_state_exposes_workflow_mode_and_enabled_phases(client, workspace, project):
    resp = client.get(_ws_url(project, "state"))
    assert resp.status_code == 200
    data = resp.json
    assert data["workflow_mode"] == "standard"
    assert "1.3" in data["enabled_phases"]
    assert "4.0" in data["enabled_phases"]


def test_state_fast_workspace_omits_optional_phases(client, workspace, project):
    client.put(_ws_url(project, "workflow-mode"), json={"mode": "fast"})

    resp = client.get(_ws_url(project, "state"))
    data = resp.json
    assert data["workflow_mode"] == "fast"
    for phase_id in ("1.3", "1.4", "4.0"):
        assert phase_id not in data["enabled_phases"]
    for phase_id in ("5.1", "5.2"):
        assert phase_id in data["enabled_phases"]


# ── workspace list GET exposure ────────────────────────────────────────────────


def test_list_workspaces_includes_workflow_mode(client, workspace, project):
    resp = client.get(f"/api/projects/{project['id']}/workspaces")
    assert resp.status_code == 200
    listed = resp.json["workspaces"]
    assert listed
    assert all("workflow_mode" in entry for entry in listed)
    assert listed[0]["workflow_mode"] == "standard"


# ── SkillConfigurator per-workspace rendering ──────────────────────────────────


def test_skill_render_differs_between_fast_and_standard_worktrees(clean_db, tmp_path):
    template = tmp_path / "skills" / "governed-workflow" / "SKILL.md.template"
    template.parent.mkdir(parents=True)
    template.write_text("---\nname: governed-workflow\ndescription: x\n---\n\n{{PHASES}}\n")

    db = get_db()
    try:
        project_id = "fast-render-project"
        root = tmp_path / "root"
        root.mkdir()
        db.execute(
            "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
            (project_id, "Render Test", str(root), datetime.now().isoformat()),
        )
        standard_dir = tmp_path / "standard-wt"
        fast_dir = tmp_path / "fast-wt"
        standard_dir.mkdir()
        fast_dir.mkdir()
        _insert_workspace(db, project_id, "feature/standard", standard_dir, "standard")
        fast_id = _insert_workspace(db, project_id, "feature/fast", fast_dir, "fast")
        workflow_mode_service.apply_mode_phase_settings(db, fast_id, "fast")
        db.commit()

        with patch.object(SkillConfigurator, "DEFAULT_TEMPLATE_PATH", template):
            SkillConfigurator().configure(db, project_id, root)

        standard_body = (standard_dir / SkillConfigurator.OUTPUT_REL_PATH).read_text()
        fast_body = (fast_dir / SkillConfigurator.OUTPUT_REL_PATH).read_text()
    finally:
        db.close()

    assert "## 4.0 Blind Code Review" in standard_body
    assert "## 4.0 Blind Code Review" not in fast_body
    assert standard_body != fast_body


# ── PlanningPhase.validate fast mode ────────────────────────────────────────────


def _set_planning_state(workspace, workflow_mode: str, execution_count: int):
    set_phase(
        workspace["id"], "2.0",
        plan_json=make_plan_json(execution_count), plan_status="approved",
        workflow_mode=workflow_mode,
    )


def test_planning_validate_fast_mode_rejects_two_execution_items(workspace, project):
    _set_planning_state(workspace, "fast", 2)

    ws = _reload_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is False
    assert "fast" in str(detail).lower()


def test_planning_validate_fast_mode_accepts_one_execution_item(workspace, project):
    _set_planning_state(workspace, "fast", 1)
    add_progress(workspace["id"], "2", "Done")

    ws = _reload_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is True, f"Expected ok but got: {detail}"


def test_planning_validate_standard_mode_accepts_two_execution_items(workspace, project):
    _set_planning_state(workspace, "standard", 2)
    add_progress(workspace["id"], "2", "Done")
    add_criterion(workspace["id"], status="accepted")

    ws = _reload_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is True, f"Expected ok but got: {detail}"


def test_planning_validate_fast_mode_skips_criteria_check(workspace, project):
    _set_planning_state(workspace, "fast", 1)
    add_progress(workspace["id"], "2", "Done")

    ws = _reload_ws(workspace["id"])
    ok, detail = PlanningPhase().validate(ws, {}, project["path"])

    assert ok is True, f"Fast mode should not require criteria, got: {detail}"


# ── Rendered SKILL.md content for fast vs standard workspaces ──────────────────


_STANDARD_ONLY_MARKERS = (
    "## 4.0 Blind Code Review",
    "## Review Item Resolution Flow",
    "1.4 (Preparation Review)",
    "3.N.3 (Code Review)",
)


def _render_workspace_skill(workspace, project):
    """Render the real (unpatched) engine template for the workspace and return its body."""
    from pathlib import Path

    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        SkillConfigurator().configure_workspace(db, proj, ws)
    finally:
        db.close()
    return Path(workspace["working_dir"], SkillConfigurator.OUTPUT_REL_PATH).read_text()


def test_fast_workspace_skill_mentions_integration_reviewer(client, workspace, project):
    client.put(_ws_url(project, "workflow-mode"), json={"mode": "fast"})

    body = _render_workspace_skill(workspace, project)

    assert "integration-reviewer" in body
    for marker in _STANDARD_ONLY_MARKERS:
        assert marker not in body, f"fast render unexpectedly contains standard-only marker: {marker!r}"


def test_standard_workspace_skill_unchanged(workspace, project):
    body = _render_workspace_skill(workspace, project)

    assert "## 4.0 Blind Code Review" in body
    assert "This workspace runs in **fast mode**" not in body
    assert "## 4.2 Final Approval (USER GATE, fast mode)" not in body
