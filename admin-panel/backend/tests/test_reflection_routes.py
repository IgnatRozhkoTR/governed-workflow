"""Tests for the reflection HTTP endpoints."""
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import reflection_service
from services.reflection_service import ReflectionStatus


def _url(workspace, path):
    return f"/api/ws/{workspace['project_id']}/feature/test/reflection/{path}"


def _seed_status(workspace_id: int, state: str) -> None:
    reflection_service._STATUS[workspace_id] = ReflectionStatus(
        workspace_id=workspace_id, state=state
    )


def _drop_status(workspace_id: int) -> None:
    reflection_service._STATUS.pop(workspace_id, None)


# ── POST /run ─────────────────────────────────────────────────────────────────


def test_post_run_returns_202_and_marks_status_running(client, workspace, monkeypatch):
    async def fake_run(db_factory, workspace_id, project_path):
        _seed_status(workspace_id, "succeeded")
        return reflection_service.get_status(workspace_id)

    monkeypatch.setattr("routes.reflection.reflection_service.run_reflection", fake_run)

    try:
        response = client.post(_url(workspace, "run"))

        assert response.status_code == 202
        data = response.get_json()
        assert data["state"] == "running"
        assert data["workspace_id"] == workspace["id"]
    finally:
        _drop_status(workspace["id"])


def test_post_run_returns_409_when_already_running(client, workspace):
    _seed_status(workspace["id"], "running")

    try:
        response = client.post(_url(workspace, "run"))

        assert response.status_code == 409
        assert response.get_json()["error"] == "reflection already running"
    finally:
        _drop_status(workspace["id"])


def test_post_run_returns_404_when_workspace_missing(client, project):
    response = client.post(f"/api/ws/{project['id']}/nonexistent-branch/reflection/run")

    assert response.status_code == 404
    assert "error" in response.get_json()


# ── GET /status ───────────────────────────────────────────────────────────────


def test_get_status_returns_dataclass_fields_as_json(client, workspace):
    _seed_status(workspace["id"], "succeeded")

    try:
        response = client.get(_url(workspace, "status"))

        assert response.status_code == 200
        data = response.get_json()
        assert data["workspace_id"] == workspace["id"]
        assert data["state"] == "succeeded"
        assert "started_at" in data
        assert "finished_at" in data
        assert "proposals_before" in data
        assert "proposals_after" in data
        assert "error" in data
        assert "agent_stdout_tail" in data
    finally:
        _drop_status(workspace["id"])


def test_get_status_includes_proposals_array(client, workspace):
    from core.db import get_db
    from services.proposal_service import create_proposal

    db = get_db()
    try:
        create_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=workspace["project_id"],
            type="rule_new",
            implementation_kind="auto",
            title="A proposal",
            body="Some body",
        )
    finally:
        db.close()

    try:
        response = client.get(_url(workspace, "status"))

        assert response.status_code == 200
        data = response.get_json()
        assert "proposals" in data
        assert isinstance(data["proposals"], list)
        assert len(data["proposals"]) == 1
        assert data["proposals"][0]["title"] == "A proposal"
    finally:
        _drop_status(workspace["id"])


# ── GET /proposals ────────────────────────────────────────────────────────────


def test_get_proposals_returns_proposals_list(client, workspace):
    from core.db import get_db
    from services.proposal_service import create_proposal

    db = get_db()
    try:
        create_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=workspace["project_id"],
            type="memory_write",
            implementation_kind="auto",
            title="Memory note",
            body="Remember this",
        )
    finally:
        db.close()

    response = client.get(_url(workspace, "proposals"))

    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["title"] == "Memory note"


def test_get_proposals_returns_empty_array_when_none(client, workspace):
    response = client.get(_url(workspace, "proposals"))

    assert response.status_code == 200
    data = response.get_json()
    assert data == []
