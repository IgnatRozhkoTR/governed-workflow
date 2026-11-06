"""Tests for the per-project "Always YOLO" setting (projects.yolo_mode_default).

Covers:
- Settings service: get/set/resolve_yolo_mode
- Settings route: GET/PUT /api/projects/<id>/settings
- create_workspace: project default, explicit override, validation
- MCP tools: none can change the setting
"""
from unittest.mock import patch

import pytest

from core.db import get_db
from services.project_settings_service import (
    ProjectSettingsError,
    get_yolo_mode_default,
    resolve_yolo_mode,
    set_yolo_mode_default,
)


def _settings_url(project):
    return f"/api/projects/{project['id']}/settings"


def _put_settings(client, project, body):
    with patch("routes.projects.ConfiguratorChain") as MockChain:
        MockChain.default.return_value.run.return_value = []
        return client.put(_settings_url(project), json=body)


def _set_project_default(project_id, enabled):
    db = get_db()
    try:
        db.execute("UPDATE projects SET yolo_mode_default = ? WHERE id = ?", (1 if enabled else 0, project_id))
        db.commit()
    finally:
        db.close()


def _create_workspace(client, project, branch, **extra):
    return client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": branch, "source": "develop", "worktree": True, **extra},
    )


def _created_yolo_mode(project_id, branch):
    db = get_db()
    try:
        row = db.execute(
            "SELECT yolo_mode FROM workspaces WHERE project_id = ? AND branch = ?",
            (project_id, branch),
        ).fetchone()
    finally:
        db.close()
    return None if row is None else row["yolo_mode"]


# ── Settings service ───────────────────────────────────────────────────────────


def test_get_yolo_mode_default_returns_false_by_default(project):
    db = get_db()
    try:
        assert get_yolo_mode_default(db, project["id"]) is False
    finally:
        db.close()


def test_set_yolo_mode_default_persists_true(project):
    db = get_db()
    try:
        set_yolo_mode_default(db, project["id"], True)
        db.commit()
        assert get_yolo_mode_default(db, project["id"]) is True
    finally:
        db.close()


def test_set_yolo_mode_default_persists_false_after_true(project):
    db = get_db()
    try:
        set_yolo_mode_default(db, project["id"], True)
        set_yolo_mode_default(db, project["id"], False)
        db.commit()
        assert get_yolo_mode_default(db, project["id"]) is False
    finally:
        db.close()


def test_get_yolo_mode_default_raises_for_unknown_project(clean_db):
    db = get_db()
    try:
        with pytest.raises(ProjectSettingsError) as exc:
            get_yolo_mode_default(db, "no-such-project")
    finally:
        db.close()
    assert exc.value.code == "project_not_found"


def test_set_yolo_mode_default_raises_for_unknown_project(clean_db):
    db = get_db()
    try:
        with pytest.raises(ProjectSettingsError) as exc:
            set_yolo_mode_default(db, "no-such-project", True)
    finally:
        db.close()
    assert exc.value.code == "project_not_found"


def test_resolve_yolo_mode_uses_project_default_when_not_requested():
    assert resolve_yolo_mode({"yolo_mode_default": 1}) is True
    assert resolve_yolo_mode({"yolo_mode_default": 0}) is False


def test_resolve_yolo_mode_explicit_false_overrides_enabled_default():
    assert resolve_yolo_mode({"yolo_mode_default": 1}, False) is False


def test_resolve_yolo_mode_explicit_true_overrides_disabled_default():
    assert resolve_yolo_mode({"yolo_mode_default": 0}, True) is True


# ── Settings route ─────────────────────────────────────────────────────────────


def test_get_settings_returns_yolo_mode_default_false_by_default(client, project):
    resp = client.get(_settings_url(project))

    assert resp.status_code == 200
    assert resp.get_json()["yolo_mode_default"] is False


def test_put_settings_updates_yolo_mode_default_alone(client, project):
    resp = _put_settings(client, project, {"yolo_mode_default": True})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["yolo_mode_default"] is True
    assert data["simple_planning"] is False
    assert data["fast_mode_default"] is False
    assert client.get(_settings_url(project)).get_json()["yolo_mode_default"] is True


def test_put_settings_can_disable_yolo_mode_default(client, project):
    _put_settings(client, project, {"yolo_mode_default": True})

    resp = _put_settings(client, project, {"yolo_mode_default": False})

    assert resp.status_code == 200
    assert resp.get_json()["yolo_mode_default"] is False
    assert client.get(_settings_url(project)).get_json()["yolo_mode_default"] is False


@pytest.mark.parametrize("other_setting", [
    {"simple_planning": True},
    {"fast_mode_default": True},
    {"review_mode_default": "integration"},
])
def test_put_other_settings_preserves_yolo_mode_default(client, project, other_setting):
    _put_settings(client, project, {"yolo_mode_default": True})

    resp = _put_settings(client, project, other_setting)

    assert resp.status_code == 200
    assert resp.get_json()["yolo_mode_default"] is True
    assert client.get(_settings_url(project)).get_json()["yolo_mode_default"] is True


def test_put_yolo_mode_default_preserves_other_settings(client, project):
    _put_settings(client, project, {"fast_mode_default": True, "simple_planning": True})

    resp = _put_settings(client, project, {"yolo_mode_default": True})

    data = resp.get_json()
    assert data["fast_mode_default"] is True
    assert data["simple_planning"] is True


@pytest.mark.parametrize("bad_value", ["yes", 1, 0, "true", [True], {"v": True}])
def test_put_settings_rejects_non_boolean_yolo_mode_default(client, project, bad_value):
    resp = client.put(_settings_url(project), json={"yolo_mode_default": bad_value})

    assert resp.status_code == 400
    assert "yolo_mode_default" in resp.get_json()["error"]


def test_put_settings_rejected_yolo_value_leaves_setting_unchanged(client, project):
    client.put(_settings_url(project), json={"yolo_mode_default": "yes"})

    assert client.get(_settings_url(project)).get_json()["yolo_mode_default"] is False


# ── create_workspace ───────────────────────────────────────────────────────────


def test_create_workspace_enables_yolo_when_project_default_on(client, project):
    _set_project_default(project["id"], True)

    resp = _create_workspace(client, project, "feature/yolo-default-on")

    assert resp.status_code == 201
    assert _created_yolo_mode(project["id"], "feature/yolo-default-on") == 1


def test_create_workspace_disables_yolo_when_project_default_off(client, project):
    resp = _create_workspace(client, project, "feature/yolo-default-off")

    assert resp.status_code == 201
    assert _created_yolo_mode(project["id"], "feature/yolo-default-off") == 0


def test_create_workspace_explicit_false_overrides_enabled_default(client, project):
    _set_project_default(project["id"], True)

    resp = _create_workspace(client, project, "feature/yolo-explicit-off", yolo_mode=False)

    assert resp.status_code == 201
    assert _created_yolo_mode(project["id"], "feature/yolo-explicit-off") == 0


def test_create_workspace_explicit_true_overrides_disabled_default(client, project):
    resp = _create_workspace(client, project, "feature/yolo-explicit-on", yolo_mode=True)

    assert resp.status_code == 201
    assert _created_yolo_mode(project["id"], "feature/yolo-explicit-on") == 1


@pytest.mark.parametrize("bad_value", ["true", 1, 0, "yes", [True]])
def test_create_workspace_rejects_non_boolean_yolo_mode(client, project, bad_value):
    resp = _create_workspace(client, project, "feature/yolo-bad", yolo_mode=bad_value)

    assert resp.status_code == 400
    assert _created_yolo_mode(project["id"], "feature/yolo-bad") is None


# ── MCP isolation ──────────────────────────────────────────────────────────────


def test_no_mcp_tool_exposes_yolo_mode_default():
    from mcp_tools import mcp

    exposing = [
        name for name, tool in mcp._tool_manager._tools.items()
        if "yolo" in name.lower() or "yolo_mode_default" in str(tool.parameters)
    ]

    assert exposing == []


def test_no_mcp_tool_writes_project_settings():
    from mcp_tools import mcp

    writers = [
        name for name, tool in mcp._tool_manager._tools.items()
        if "project_settings" in tool.fn.__module__ or "set_yolo_mode_default" in tool.fn.__code__.co_names
    ]

    assert writers == []
