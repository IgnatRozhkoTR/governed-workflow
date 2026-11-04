"""Tests for the asynchronous LSP start/stop routes and status reaping.

Every test here stubs out the real subprocess spawn/handshake seam
(``lsp_service._start_lsp_server_body``) or supplies a fake process object,
so no real LSP binary is ever launched.
"""
import subprocess
import threading
import time
from datetime import datetime

import pytest

from core.db import get_db
from services import lsp_service


def _start_url(project_id, branch):
    return f"/api/ws/{project_id}/{branch}/lsp/start"


def _stop_url(project_id, branch):
    return f"/api/ws/{project_id}/{branch}/lsp/stop"


def _status_url(project_id, branch):
    return f"/api/ws/{project_id}/{branch}/lsp/status"


def _create_lsp_profile(project_id, has_lsp_command=True):
    """Insert a user verification profile (optionally LSP-capable) assigned to *project_id*."""
    db = get_db()
    try:
        lsp_command = "fake-lsp-server" if has_lsp_command else None
        cursor = db.execute(
            "INSERT INTO verification_profiles (name, language, origin, lsp_command, lsp_args, created_at) "
            "VALUES ('Test LSP Profile', 'python', 'user', ?, '[]', ?)",
            (lsp_command, datetime.now().isoformat())
        )
        profile_id = cursor.lastrowid
        db.execute(
            "INSERT INTO project_verification_profiles (project_id, profile_id, subpath, lsp_enabled) "
            "VALUES (?, ?, '.', 1)",
            (project_id, profile_id)
        )
        db.commit()
        return profile_id
    finally:
        db.close()


def _set_lsp_status(project_id, profile_id, status, pid=None):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO lsp_instances (project_id, profile_id, status, pid) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(project_id, profile_id) DO UPDATE SET status = ?, pid = ?",
            (project_id, profile_id, status, pid, status, pid)
        )
        db.commit()
    finally:
        db.close()


def _get_lsp_row(project_id, profile_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM lsp_instances WHERE project_id = ? AND profile_id = ?",
            (project_id, profile_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def _wait_until(predicate, timeout=3.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture(autouse=True)
def clean_lsp_process_registry():
    """Ensure module-level process/lock registries don't leak fake entries across tests."""
    yield
    lsp_service._LSP_PROCESSES.clear()
    lsp_service._PROCESS_LOCKS.clear()


class _ControlledStartBody:
    """Stand-in for ``_start_lsp_server_body`` that blocks until the test releases it."""

    def __init__(self, final_status="running", final_pid=4321):
        self.started = threading.Event()
        self.proceed = threading.Event()
        self.final_status = final_status
        self.final_pid = final_pid

    def __call__(self, db, project_id, profile_id, workspace_path, key):
        self.started.set()
        self.proceed.wait(timeout=5)
        db.execute(
            "UPDATE lsp_instances SET status = ?, pid = ?, error_message = NULL "
            "WHERE project_id = ? AND profile_id = ?",
            (self.final_status, self.final_pid, project_id, profile_id)
        )
        db.commit()


class _ControlledFakeProcess:
    """Fake ``subprocess.Popen`` handle for exercising the stop lifecycle without a real process."""

    def __init__(self, pid):
        self.pid = pid
        self.terminated_event = threading.Event()
        self.release_event = threading.Event()

    def terminate(self):
        self.terminated_event.set()

    def wait(self, timeout=None):
        if not self.release_event.wait(timeout=timeout):
            raise subprocess.TimeoutExpired(cmd="fake-lsp-server", timeout=timeout or 0)
        return 0


def test_start_returns_202_immediately_with_starting_status(client, workspace, monkeypatch):
    profile_id = _create_lsp_profile(workspace["project_id"])
    controlled = _ControlledStartBody()
    monkeypatch.setattr(lsp_service, "_start_lsp_server_body", controlled)

    resp = client.post(
        _start_url(workspace["project_id"], workspace["branch"]),
        json={"profile_id": profile_id},
    )

    assert resp.status_code == 202
    assert resp.json["status"] == "starting"
    assert resp.json["profile_id"] == profile_id

    assert controlled.started.wait(timeout=2)
    row = _get_lsp_row(workspace["project_id"], profile_id)
    assert row["status"] == "starting"

    controlled.proceed.set()
    assert _wait_until(
        lambda: _get_lsp_row(workspace["project_id"], profile_id)["status"] == "running"
    )


def test_start_returns_400_when_profile_has_no_lsp_command(client, workspace):
    profile_id = _create_lsp_profile(workspace["project_id"], has_lsp_command=False)

    resp = client.post(
        _start_url(workspace["project_id"], workspace["branch"]),
        json={"profile_id": profile_id},
    )

    assert resp.status_code == 400
    assert resp.json["error"] == "profile_has_no_lsp_command"


def test_duplicate_start_while_starting_is_a_noop_200(client, workspace, monkeypatch):
    profile_id = _create_lsp_profile(workspace["project_id"])
    controlled = _ControlledStartBody()
    monkeypatch.setattr(lsp_service, "_start_lsp_server_body", controlled)

    first = client.post(
        _start_url(workspace["project_id"], workspace["branch"]),
        json={"profile_id": profile_id},
    )
    assert first.status_code == 202
    assert controlled.started.wait(timeout=2)

    second = client.post(
        _start_url(workspace["project_id"], workspace["branch"]),
        json={"profile_id": profile_id},
    )
    assert second.status_code == 200
    assert second.json["status"] == "starting"
    assert second.json.get("no_op") is True

    controlled.proceed.set()
    assert _wait_until(
        lambda: _get_lsp_row(workspace["project_id"], profile_id)["status"] == "running"
    )


def test_stop_writes_stopping_then_stopped(client, workspace):
    profile_id = _create_lsp_profile(workspace["project_id"])
    _set_lsp_status(workspace["project_id"], profile_id, status="running", pid=4321)

    key = lsp_service._process_key(workspace["project_id"], profile_id)
    fake_process = _ControlledFakeProcess(pid=4321)
    lsp_service._LSP_PROCESSES[key] = {
        "process": fake_process,
        "profile_id": profile_id,
        "project_id": workspace["project_id"],
        "workspace_path": workspace["working_dir"],
    }

    resp = client.post(
        _stop_url(workspace["project_id"], workspace["branch"]),
        json={"profile_id": profile_id},
    )

    assert resp.status_code == 202
    assert resp.json["status"] == "stopping"

    assert fake_process.terminated_event.wait(timeout=2)
    row = _get_lsp_row(workspace["project_id"], profile_id)
    assert row["status"] == "stopping"

    fake_process.release_event.set()
    assert _wait_until(
        lambda: _get_lsp_row(workspace["project_id"], profile_id)["status"] == "stopped"
    )
    final_row = _get_lsp_row(workspace["project_id"], profile_id)
    assert final_row["pid"] is None


def test_reaper_captures_real_returncode_for_tracked_process(client, workspace):
    profile_id = _create_lsp_profile(workspace["project_id"])
    dead_pid = 2147483647  # out of realistic pid range; guaranteed not alive
    _set_lsp_status(workspace["project_id"], profile_id, status="running", pid=dead_pid)

    key = lsp_service._process_key(workspace["project_id"], profile_id)

    class _DeadProcessStub:
        def poll(self):
            return 137

    lsp_service._LSP_PROCESSES[key] = {
        "process": _DeadProcessStub(),
        "profile_id": profile_id,
        "project_id": workspace["project_id"],
        "workspace_path": workspace["working_dir"],
    }

    resp = client.get(_status_url(workspace["project_id"], workspace["branch"]))
    assert resp.status_code == 200

    entry = next(e for e in resp.json if e["profile_id"] == profile_id)
    assert entry["status"] == "error"
    assert entry["error_message"] == "LSP server exited with return code 137"
    assert key not in lsp_service._LSP_PROCESSES


def test_reaper_uses_generic_message_for_untracked_dead_pid(client, workspace):
    profile_id = _create_lsp_profile(workspace["project_id"])
    dead_pid = 2147483646
    _set_lsp_status(workspace["project_id"], profile_id, status="running", pid=dead_pid)

    resp = client.get(_status_url(workspace["project_id"], workspace["branch"]))
    assert resp.status_code == 200

    entry = next(e for e in resp.json if e["profile_id"] == profile_id)
    assert entry["status"] == "error"
    assert entry["error_message"] == "Process died unexpectedly"
