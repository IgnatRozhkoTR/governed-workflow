"""Transaction-boundary and failure-path tests for verification runs."""
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import pytest

from core import db as db_module
from core.db import get_db
from services import verification_service


def _assign_step(project_id, command, timeout=10, fail_severity="blocking", install_check_command=None):
    db = get_db()
    try:
        profile_id = verification_service.create_profile(db, "Txn Profile", "shell")["id"]
        verification_service.add_step(
            db, profile_id, "Step", command, timeout=timeout, fail_severity=fail_severity,
            install_check_command=install_check_command,
        )
        verification_service.assign_profile(db, project_id, profile_id)
        db.commit()
    finally:
        db.close()


def _run(workspace):
    db = get_db()
    try:
        return verification_service.run_verification(db, workspace["id"], "3.1.1", workspace["working_dir"])
    finally:
        db.close()


def _load_run(workspace_id, run_id=None):
    db = get_db()
    try:
        if run_id is None:
            return dict(db.execute(
                "SELECT * FROM verification_runs WHERE workspace_id = ? ORDER BY id DESC LIMIT 1",
                (workspace_id,)
            ).fetchone())
        return verification_service.get_verification_results(db, workspace_id, run_id=run_id)
    finally:
        db.close()


def _wait_for(path, deadline_seconds=5):
    deadline = time.time() + deadline_seconds
    while not Path(path).exists():
        if time.time() > deadline:
            pytest.fail(f"step never started: {path} missing")
        time.sleep(0.02)


def _write_with_short_busy_timeout():
    other = sqlite3.connect(str(db_module.DB_PATH), timeout=0.2)
    try:
        other.execute("PRAGMA busy_timeout = 200")
        other.execute(
            "INSERT INTO verification_profiles (name, language, origin, created_at) "
            "VALUES ('Concurrent', 'shell', 'user', '2026-01-01')"
        )
        other.commit()
        return other.execute("SELECT status FROM verification_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    finally:
        other.close()


def test_run_verification_allows_concurrent_writes_while_step_runs(workspace, project, tmp_path):
    """A second connection can write while a verification step is still sleeping."""
    marker = tmp_path / "started.flag"
    _assign_step(project["id"], f"touch '{marker}' && sleep 1")
    runner = threading.Thread(target=_run, args=(workspace,))
    runner.start()
    try:
        _wait_for(marker)
        visible_status = _write_with_short_busy_timeout()
    finally:
        runner.join()

    assert visible_status == "running"
    assert _load_run(workspace["id"])["status"] == "passed"


def test_run_verification_records_timeout_as_failed_run(workspace, project):
    """A blocking step that times out yields a failed step and a completed failed run."""
    _assign_step(project["id"], "sleep 5", timeout=1)

    passed, run_id = _run(workspace)

    run = _load_run(workspace["id"], run_id)
    assert passed is False
    assert run["status"] == "failed"
    assert run["completed_at"] is not None
    assert run["steps"][0]["status"] == "failed"
    assert "Timed out after 1s" in run["steps"][0]["output"]


def test_run_verification_records_warning_timeout_without_failing_run(workspace, project):
    """A warning-severity timeout is recorded as a warning and the run still passes."""
    _assign_step(project["id"], "sleep 5", timeout=1, fail_severity="warning")

    passed, run_id = _run(workspace)

    run = _load_run(workspace["id"], run_id)
    assert passed is True
    assert run["status"] == "passed"
    assert run["steps"][0]["status"] == "warning"


def test_run_verification_records_install_check_timeout_as_failed_step(workspace, project, monkeypatch):
    """An install-check timeout no longer escapes; the step and run are recorded as failed."""
    _assign_step(project["id"], "echo ok", install_check_command="slow-check")

    def timing_out_shell(command, cwd, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(verification_service, "_shell", timing_out_shell)

    passed, run_id = _run(workspace)

    run = _load_run(workspace["id"], run_id)
    assert passed is False
    assert run["status"] == "failed"
    assert run["steps"][0]["status"] == "failed"
    assert "Timed out after 10s" in run["steps"][0]["output"]


def test_run_verification_marks_run_failed_when_unexpected_error_escapes(workspace, project, monkeypatch):
    """An unexpected exception propagates but the run is finalized as failed, not left running."""
    _assign_step(project["id"], "echo ok")

    def exploding_step(step, step_dir):
        raise RuntimeError("boom")

    monkeypatch.setattr(verification_service, "_execute_step", exploding_step)

    with pytest.raises(RuntimeError, match="boom"):
        _run(workspace)

    run = _load_run(workspace["id"])
    assert run["status"] == "failed"
    assert run["completed_at"] is not None
