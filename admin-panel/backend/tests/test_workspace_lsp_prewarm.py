"""Tests for the LSP pre-warm-on-creation feature in create_workspace.

The pre-warm path reuses lsp_service.start_all_lsp_servers_async, so these
tests stub the same background-spawn seam (_start_lsp_server_body) used by
test_lsp_routes.py rather than launching a real LSP binary.
"""
import os
import time
from datetime import datetime

import pytest

from core.db import get_db
from services import lsp_service


def _wait_until(predicate, timeout=3.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _lsp_status(project_id, profile_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT status FROM lsp_instances WHERE project_id = ? AND profile_id = ?",
            (project_id, profile_id)
        ).fetchone()
        return row["status"] if row else None
    finally:
        db.close()


def _create_lsp_profile(project_id, name="Prewarm Profile", lsp_enabled=1, has_lsp_command=True):
    db = get_db()
    try:
        lsp_command = "fake-lsp-server" if has_lsp_command else None
        cursor = db.execute(
            "INSERT INTO verification_profiles (name, language, origin, lsp_command, lsp_args, created_at) "
            "VALUES (?, 'python', 'user', ?, '[]', ?)",
            (name, lsp_command, datetime.now().isoformat())
        )
        profile_id = cursor.lastrowid
        db.execute(
            "INSERT INTO project_verification_profiles (project_id, profile_id, subpath, lsp_enabled) "
            "VALUES (?, ?, '.', ?)",
            (project_id, profile_id, lsp_enabled)
        )
        db.commit()
        return profile_id
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_lsp_process_registry():
    yield
    lsp_service._LSP_PROCESSES.clear()
    lsp_service._PROCESS_LOCKS.clear()


@pytest.fixture(autouse=True)
def enable_prewarm_for_this_module(monkeypatch):
    """These tests exercise pre-warm directly, so undo the suite-wide kill switch."""
    monkeypatch.delenv("GOVERNED_WORKFLOW_DISABLE_LSP_PREWARM", raising=False)


def test_create_workspace_starts_assigned_lsp_enabled_profiles(client, project, monkeypatch):
    profile_id = _create_lsp_profile(project["id"], name="Prewarm A")

    started = []

    def fake_start_body(db, project_id, profile_id, workspace_path, key):
        started.append(profile_id)
        db.execute(
            "UPDATE lsp_instances SET status = 'running', pid = 999 "
            "WHERE project_id = ? AND profile_id = ?",
            (project_id, profile_id)
        )
        db.commit()

    monkeypatch.setattr(lsp_service, "_start_lsp_server_body", fake_start_body)

    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/prewarm-a", "source": "develop", "worktree": True},
    )

    assert resp.status_code == 201
    assert resp.json["lsp_prewarm"]["skipped_reason"] is None
    assert resp.json["lsp_prewarm"]["started"] == ["Prewarm A"]


def test_create_workspace_skips_disabled_profile_assignment(client, project, monkeypatch):
    _create_lsp_profile(project["id"], name="Disabled Profile", lsp_enabled=0)
    monkeypatch.setattr(
        lsp_service, "_start_lsp_server_body",
        lambda db, project_id, profile_id, workspace_path, key: None,
    )

    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/prewarm-disabled", "source": "develop", "worktree": True},
    )

    assert resp.status_code == 201
    assert resp.json["lsp_prewarm"] == {"started": [], "skipped_reason": "no_lsp_enabled_profiles"}


def test_create_workspace_reports_no_profiles_when_none_assigned(client, project):
    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/prewarm-none", "source": "develop", "worktree": True},
    )

    assert resp.status_code == 201
    assert resp.json["lsp_prewarm"] == {"started": [], "skipped_reason": "no_lsp_enabled_profiles"}


def test_create_workspace_succeeds_even_when_prewarm_raises(client, project, monkeypatch):
    _create_lsp_profile(project["id"], name="Boom Profile")

    def _boom(db, project_id, workspace_path):
        raise RuntimeError("prewarm exploded")

    monkeypatch.setattr(lsp_service, "start_all_lsp_servers_async", _boom)

    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/prewarm-boom", "source": "develop", "worktree": True},
    )

    assert resp.status_code == 201
    assert resp.json["lsp_prewarm"] == {"started": [], "skipped_reason": "prewarm_failed"}


def test_create_workspace_honors_disable_prewarm_kill_switch(client, project, monkeypatch):
    _create_lsp_profile(project["id"], name="Killed Profile")
    monkeypatch.setenv("GOVERNED_WORKFLOW_DISABLE_LSP_PREWARM", "1")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("start_all_lsp_servers_async must not be called when pre-warm is disabled")

    monkeypatch.setattr(lsp_service, "start_all_lsp_servers_async", _fail_if_called)

    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/prewarm-killed", "source": "develop", "worktree": True},
    )

    assert resp.status_code == 201
    assert resp.json["lsp_prewarm"] == {"started": [], "skipped_reason": "disabled_by_env"}


def test_prewarm_followed_by_user_start_click_is_a_clean_noop(client, project, monkeypatch):
    profile_id = _create_lsp_profile(project["id"], name="Noop Profile")
    own_pid = os.getpid()

    def fake_start_body(db, project_id, profile_id, workspace_path, key):
        lsp_service._LSP_PROCESSES[key] = {
            "process": object(),
            "profile_id": profile_id,
            "project_id": project_id,
            "workspace_path": workspace_path,
        }
        db.execute(
            "UPDATE lsp_instances SET status = 'running', pid = ? "
            "WHERE project_id = ? AND profile_id = ?",
            (own_pid, project_id, profile_id)
        )
        db.commit()

    monkeypatch.setattr(lsp_service, "_start_lsp_server_body", fake_start_body)

    resp = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/prewarm-noop", "source": "develop", "worktree": True},
    )
    assert resp.status_code == 201
    branch = resp.json["branch"]

    assert _wait_until(lambda: _lsp_status(project["id"], profile_id) == "running")

    click_resp = client.post(
        f"/api/ws/{project['id']}/{branch}/lsp/start",
        json={"profile_id": profile_id},
    )

    assert click_resp.status_code == 200
    assert click_resp.json["status"] == "already_running"
