"""Tests for session hook routes."""
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
    set_phase(workspace["id"], "3.1.0", yolo_mode=1, scope_status="pending")
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
    file is rejected."""
    import json as _json
    scope = _json.dumps({"3.1": {"must": ["src/"], "may": []}})
    plan = (
        '{"description":"p","systemDiagram":"","execution":'
        '[{"id":"3.1","name":"N","tasks":[{"title":"T","files":[]}]}]}'
    )
    set_phase(
        workspace["id"], "3.1.0",
        yolo_mode=0,
        scope_json=scope,
        scope_status="approved",
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
