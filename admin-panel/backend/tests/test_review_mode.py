"""Tests for the per-workspace review_mode enum setting.

Covers:
- Migration 0050: workspaces.review_mode + projects.review_mode_default columns
- review_mode_service: strategy mapping, validation, column update, creation
  default resolution — and that it never touches phase_settings
- PUT /api/ws/<project>/<branch>/review-mode route
- create_workspace honoring explicit review_mode and project review_mode_default
- state GET exposing review_mode
- workspace list GET exposing review_mode
- MCP workspace_get_state exposing review_mode
- Project settings GET/PUT exposing review_mode_default
"""
from datetime import datetime

import pytest

from core.db import get_db
from services import review_mode_service
from services.phase_settings import get_scope_settings
from services.project_settings_service import (
    ProjectSettingsError,
    get_review_mode_default,
    set_review_mode_default,
)


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


# ── Migration 0050 ──────────────────────────────────────────────────────────────


def test_migration_0050_adds_both_columns():
    db = get_db()
    try:
        ws_cols = {r[1] for r in db.execute("PRAGMA table_info(workspaces)").fetchall()}
        proj_cols = {r[1] for r in db.execute("PRAGMA table_info(projects)").fetchall()}
    finally:
        db.close()
    assert "review_mode" in ws_cols
    assert "review_mode_default" in proj_cols


def test_migration_0050_defaults(project, workspace):
    ws = _reload_ws(workspace["id"])
    proj = _reload_project(project["id"])
    assert ws["review_mode"] == "files_integration"
    assert proj["review_mode_default"] == "files_integration"


# ── review_mode_service: strategy mapping ────────────────────────────────────────


def test_strategies_for_manual_is_empty():
    ws = {"review_mode": "manual"}
    assert review_mode_service.strategies_for(ws) == frozenset()


def test_strategies_for_integration_only():
    ws = {"review_mode": "integration"}
    assert review_mode_service.strategies_for(ws) == frozenset({"integration"})


def test_strategies_for_files_integration():
    ws = {"review_mode": "files_integration"}
    assert review_mode_service.strategies_for(ws) == frozenset({"files", "integration"})


def test_strategies_for_full():
    ws = {"review_mode": "full"}
    assert review_mode_service.strategies_for(ws) == frozenset(
        {"files", "integration", "adjudication"}
    )


def test_strategies_for_missing_column_defaults_to_files_integration():
    """Rows loaded before migration 0050 (or plain dicts in unit tests) have no
    ``review_mode`` key — ``ws_field`` falls back to the documented default."""
    ws = {}
    assert review_mode_service.strategies_for(ws) == frozenset({"files", "integration"})


# ── review_mode_service: validation + resolution ─────────────────────────────────


def test_resolve_default_review_mode_explicit_wins():
    project = {"review_mode_default": "manual"}
    assert review_mode_service.resolve_default_review_mode(project, "full") == "full"


def test_resolve_default_review_mode_uses_project_default():
    project = {"review_mode_default": "integration"}
    assert review_mode_service.resolve_default_review_mode(project) == "integration"


def test_resolve_default_review_mode_falls_back_when_project_missing_column():
    assert review_mode_service.resolve_default_review_mode({}) == "files_integration"


def test_resolve_default_review_mode_rejects_invalid_explicit():
    project = {"review_mode_default": "files_integration"}
    with pytest.raises(ValueError):
        review_mode_service.resolve_default_review_mode(project, "turbo")


# ── review_mode_service: set_workspace_review_mode ───────────────────────────────


def test_set_workspace_review_mode_updates_column(workspace):
    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        review_mode_service.set_workspace_review_mode(db, ws, "full")
        db.commit()
    finally:
        db.close()

    assert _reload_ws(workspace["id"])["review_mode"] == "full"


def test_set_workspace_review_mode_rejects_invalid_mode(workspace):
    db = get_db()
    try:
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        with pytest.raises(ValueError):
            review_mode_service.set_workspace_review_mode(db, ws, "nope")
    finally:
        db.close()


def test_set_workspace_review_mode_does_not_touch_phase_settings(workspace):
    """Unlike workflow_mode, review_mode is a plain column update — no
    phase_settings disable rows and no configurator rerun."""
    db = get_db()
    try:
        before = get_scope_settings(db, "workspace", str(workspace["id"]))
        ws = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace["id"],)).fetchone()
        review_mode_service.set_workspace_review_mode(db, ws, "manual")
        db.commit()
        after = get_scope_settings(db, "workspace", str(workspace["id"]))
    finally:
        db.close()
    assert before == after == {}


# ── Route: PUT /review-mode ───────────────────────────────────────────────────────


def test_put_review_mode_round_trips_all_valid_modes(client, workspace, project):
    for mode in review_mode_service.VALID_REVIEW_MODES:
        resp = client.put(_ws_url(project, "review-mode"), json={"mode": mode})
        assert resp.status_code == 200
        assert resp.json["mode"] == mode
        assert _reload_ws(workspace["id"])["review_mode"] == mode


def test_put_review_mode_rejects_invalid(client, workspace, project):
    resp = client.put(_ws_url(project, "review-mode"), json={"mode": "turbo"})
    assert resp.status_code == 400


def test_put_review_mode_unknown_workspace(client, project):
    resp = client.put(
        f"/api/ws/{project['id']}/feature/nonexistent/review-mode",
        json={"mode": "manual"},
    )
    assert resp.status_code == 404


# ── create_workspace review_mode resolution ───────────────────────────────────────


def _created_ws(project_id, branch):
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM workspaces WHERE project_id = ? AND branch = ?",
            (project_id, branch),
        ).fetchone()
    finally:
        db.close()


def test_create_workspace_honors_explicit_review_mode(client, project):
    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/explicit-review-manual", "source": "develop",
              "worktree": True, "review_mode": "manual"},
    )
    assert resp.status_code == 201
    ws = _created_ws(project["id"], "feature/explicit-review-manual")
    assert ws["review_mode"] == "manual"


def test_create_workspace_uses_project_review_mode_default(client, project):
    db = get_db()
    try:
        db.execute(
            "UPDATE projects SET review_mode_default = 'full' WHERE id = ?", (project["id"],)
        )
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/default-review-full", "source": "develop", "worktree": True},
    )
    assert resp.status_code == 201
    assert _created_ws(project["id"], "feature/default-review-full")["review_mode"] == "full"


def test_create_workspace_defaults_to_files_integration(client, project):
    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/default-review-standard", "source": "develop", "worktree": True},
    )
    assert resp.status_code == 201
    ws = _created_ws(project["id"], "feature/default-review-standard")
    assert ws["review_mode"] == "files_integration"


def test_create_workspace_rejects_invalid_review_mode(client, project):
    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/bad-review-mode", "source": "develop",
              "worktree": True, "review_mode": "turbo"},
    )
    assert resp.status_code == 400


# ── state GET exposure ─────────────────────────────────────────────────────────────


def test_state_exposes_review_mode(client, workspace, project):
    resp = client.get(_ws_url(project, "state"))
    assert resp.status_code == 200
    assert resp.json["review_mode"] == "files_integration"


def test_state_reflects_updated_review_mode(client, workspace, project):
    client.put(_ws_url(project, "review-mode"), json={"mode": "manual"})
    resp = client.get(_ws_url(project, "state"))
    assert resp.json["review_mode"] == "manual"


# ── workspace list GET exposure ─────────────────────────────────────────────────────


def test_list_workspaces_includes_review_mode(client, workspace, project):
    resp = client.get(f"/api/projects/{project['id']}/workspaces")
    assert resp.status_code == 200
    listed = resp.json["workspaces"]
    assert listed
    assert all("review_mode" in entry for entry in listed)
    assert listed[0]["review_mode"] == "files_integration"


# ── MCP workspace_get_state exposure ──────────────────────────────────────────────


def test_mcp_get_state_exposes_review_mode(workspace, monkeypatch):
    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_get_state
    result = workspace_get_state()
    assert result["review_mode"] == "files_integration"


def test_mcp_get_state_reflects_updated_review_mode(client, workspace, project, monkeypatch):
    client.put(_ws_url(project, "review-mode"), json={"mode": "full"})
    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_get_state
    result = workspace_get_state()
    assert result["review_mode"] == "full"


# ── Project settings GET/PUT exposure ──────────────────────────────────────────────


def test_get_project_settings_returns_review_mode_default(client, project):
    resp = client.get(f"/api/projects/{project['id']}/settings")
    assert resp.status_code == 200
    assert resp.json["review_mode_default"] == "files_integration"


def test_put_project_settings_updates_review_mode_default(client, project):
    resp = client.put(
        f"/api/projects/{project['id']}/settings",
        json={"simple_planning": False, "review_mode_default": "integration"},
    )
    assert resp.status_code == 200
    assert resp.json["review_mode_default"] == "integration"
    assert _reload_project(project["id"])["review_mode_default"] == "integration"


def test_put_project_settings_rejects_invalid_review_mode_default(client, project):
    resp = client.put(
        f"/api/projects/{project['id']}/settings",
        json={"simple_planning": False, "review_mode_default": "turbo"},
    )
    assert resp.status_code == 400


def test_put_project_settings_omitted_review_mode_default_preserves_existing(client, project):
    db = get_db()
    try:
        set_review_mode_default(db, project["id"], "full")
        db.commit()
    finally:
        db.close()

    resp = client.put(
        f"/api/projects/{project['id']}/settings",
        json={"simple_planning": False},
    )
    assert resp.status_code == 200
    assert resp.json["review_mode_default"] == "full"


def test_service_get_review_mode_default_raises_for_unknown_project():
    db = get_db()
    try:
        with pytest.raises(ProjectSettingsError):
            get_review_mode_default(db, "does-not-exist")
    finally:
        db.close()


def test_service_set_review_mode_default_rejects_invalid_mode(project):
    db = get_db()
    try:
        with pytest.raises(ProjectSettingsError):
            set_review_mode_default(db, project["id"], "turbo")
    finally:
        db.close()
