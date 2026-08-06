"""Tests for session hook routes."""
from pathlib import Path
from unittest.mock import patch

from testing_utils import _git, set_phase


def test_session_start_success(client, workspace):
    _git(workspace["working_dir"], "checkout", "-b", "feature/test")
    r = client.post(
        "/api/hook/session-start",
        json={"session_id": "sess-123", "cwd": workspace["working_dir"]},
    )
    assert r.status_code == 200
    assert r.json["ok"] is True

    from core.db import get_db
    db = get_db()
    row = db.execute(
        "SELECT session_id FROM workspaces WHERE id = ?", (workspace["id"],)
    ).fetchone()
    db.close()
    assert row["session_id"] == "sess-123"


def test_session_start_no_session_id(client):
    r = client.post("/api/hook/session-start", json={"cwd": "/tmp"})
    assert r.status_code == 400
    assert "session_id" in r.json["error"].lower()


def test_session_start_no_workspace(client, project, git_repo):
    # git_repo is on develop; no workspace registered for develop branch
    r = client.post(
        "/api/hook/session-start",
        json={"session_id": "sess-789", "cwd": git_repo},
    )
    assert r.status_code == 200
    assert r.json["ok"] is False


def test_session_start_no_git_repo(client, tmp_path):
    r = client.post(
        "/api/hook/session-start",
        json={"session_id": "sess-456", "cwd": str(tmp_path)},
    )
    assert r.status_code == 200
    assert r.json["ok"] is False


def test_session_start_records_history(client, workspace):
    _git(workspace["working_dir"], "checkout", "-b", "feature/test")

    client.post(
        "/api/hook/session-start",
        json={"session_id": "sess-first", "cwd": workspace["working_dir"]},
    )
    client.post(
        "/api/hook/session-start",
        json={"session_id": "sess-second", "cwd": workspace["working_dir"]},
    )

    from core.db import get_db
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM session_history WHERE workspace_id = ?", (workspace["id"],)
    ).fetchone()[0]
    db.close()
    assert count == 2


def test_session_start_deduplicates(client, workspace):
    _git(workspace["working_dir"], "checkout", "-b", "feature/test")

    client.post(
        "/api/hook/session-start",
        json={"session_id": "sess-dup", "cwd": workspace["working_dir"]},
    )
    client.post(
        "/api/hook/session-start",
        json={"session_id": "sess-dup", "cwd": workspace["working_dir"]},
    )

    from core.db import get_db
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM session_history WHERE workspace_id = ? AND session_id = 'sess-dup'",
        (workspace["id"],)
    ).fetchone()[0]
    db.close()
    assert count == 1


def test_yolo_mode_bypasses_scope_matching(client, workspace):
    """When yolo_mode is set, ``check-permission`` allows any tool+file
    without consulting scope patterns."""
    set_phase(workspace["id"], "3.1.0", yolo_mode=1)
    r = client.post(
        "/api/hook/check-permission",
        json={
            "cwd": workspace["working_dir"],
            "tool_name": "Edit",
            "file_path": "unauthorized/evil.py",
        },
    )
    assert r.status_code == 200
    assert r.json == {"governed": True, "allowed": True}


def test_scope_enforced_when_yolo_disabled(client, workspace):
    """Without yolo, ``check-permission`` enforces scope so an out-of-scope
    file is rejected. Scope lives inside the plan execution item."""
    plan = (
        '{"description":"p","systemDiagram":"","execution":'
        '[{"id":"3.1","name":"N","scope":{"must":["src/"],"may":[]},'
        '"tasks":[{"title":"T","files":[]}]}]}'
    )
    set_phase(
        workspace["id"], "3.1.0",
        yolo_mode=0,
        plan_json=plan,
        plan_status="approved",
    )
    r = client.post(
        "/api/hook/check-permission",
        json={
            "cwd": workspace["working_dir"],
            "tool_name": "Edit",
            "file_path": "unauthorized/evil.py",
        },
    )
    assert r.status_code == 200
    assert r.json["governed"] is True
    assert r.json["allowed"] is False


def test_edit_tool_blocked_from_governed_workflow_install(client, workspace):
    """Edit/Write targeting any file inside the governed-workflow install tree
    is denied from a user workspace, even with yolo mode enabled."""
    set_phase(workspace["id"], "3.1.0", yolo_mode=1)

    from core.paths import REPO_ROOT
    evil_target = str(REPO_ROOT / "admin-panel" / "backend" / "admin-panel.db")

    r = client.post(
        "/api/hook/check-permission",
        json={
            "cwd": workspace["working_dir"],
            "tool_name": "Write",
            "file_path": evil_target,
        },
    )
    assert r.status_code == 200
    assert r.json["governed"] is True
    assert r.json["allowed"] is False
    assert "governed-workflow installation" in r.json["reason"]


def test_bash_command_blocked_when_referencing_governed_workflow_path(client, workspace):
    """Bash commands that reference a governed-workflow path (even via cat or
    python) are denied from a user workspace."""
    set_phase(workspace["id"], "3.1.0", yolo_mode=1)

    from core.paths import REPO_ROOT
    command = f"cat {REPO_ROOT}/admin-panel/backend/admin-panel.db"

    r = client.post(
        "/api/hook/check-permission",
        json={
            "cwd": workspace["working_dir"],
            "tool_name": "Bash",
            "command": command,
        },
    )
    assert r.status_code == 200
    assert r.json["governed"] is True
    assert r.json["allowed"] is False


def test_edit_tool_allowed_inside_governed_workflow_self_workspace(
    client, project, git_repo, tmp_path, monkeypatch
):
    """A workspace whose working_dir sits inside the governed-workflow install
    IS allowed to modify governed-workflow files — that's the self-edit path
    for people developing the admin panel itself."""
    from core.db import get_db
    from core.paths import REPO_ROOT

    # Simulate a workspace whose working_dir is inside REPO_ROOT (a hypothetical
    # .claude/worktrees subdirectory of the governed-workflow repo itself).
    self_wd = str(REPO_ROOT / ".claude" / "worktrees" / "test-self")

    db = get_db()
    from datetime import datetime
    now = datetime.now().isoformat()
    cursor = db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch, yolo_mode) "
        "VALUES (?, ?, ?, ?, ?, 'active', '3.1.0', ?, ?, 1)",
        (
            project["id"], "self-edit", "self-edit", self_wd, now,
            '{"description":"","systemDiagram":"","execution":[]}', "main"
        )
    )
    ws_id = cursor.lastrowid
    db.commit()
    db.close()

    target = str(REPO_ROOT / "admin-panel" / "backend" / "app.py")
    r = client.post(
        "/api/hook/check-permission",
        json={
            "cwd": self_wd,
            "tool_name": "Write",
            "file_path": target,
        },
    )
    # Under yolo the check early-returns as allowed; the point is it is NOT
    # blocked by the new governed-workflow path guard.
    assert r.status_code == 200
    assert r.json["allowed"] is True


def test_session_start_dispatches_kickoff_when_marker_present(client, workspace):
    """When a kickoff-pending marker exists in the workspace state dir,
    session_start_hook deletes it and calls send_prompt_when_ready with the
    correct session name and continue prompt."""
    from core.terminal import session_name

    _git(workspace["working_dir"], "checkout", "-b", "feature/test")

    marker = Path(workspace["working_dir"]) / ".claude" / "state" / "kickoff-pending"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("")

    expected_session = session_name(workspace["project_id"], workspace["sanitized_branch"])

    with patch("routes.hooks.send_prompt_when_ready") as mock_send:
        r = client.post(
            "/api/hook/session-start",
            json={"session_id": "sess-kickoff", "cwd": workspace["working_dir"]},
        )

    assert r.status_code == 200
    assert r.json["ok"] is True
    mock_send.assert_called_once_with(expected_session, "Continue with the next phase.")
    assert not marker.exists()


def test_session_start_no_kickoff_without_marker(client, workspace):
    """When no kickoff-pending marker exists, send_prompt_when_ready is not
    called during session_start_hook."""
    _git(workspace["working_dir"], "checkout", "-b", "feature/test")

    marker = Path(workspace["working_dir"]) / ".claude" / "state" / "kickoff-pending"
    assert not marker.exists()

    with patch("routes.hooks.send_prompt_when_ready") as mock_send:
        r = client.post(
            "/api/hook/session-start",
            json={"session_id": "sess-no-kickoff", "cwd": workspace["working_dir"]},
        )

    assert r.status_code == 200
    assert r.json["ok"] is True
    mock_send.assert_not_called()
