"""Tests for project CRUD endpoints."""
import json
import pytest

from services import lsp_service
from testing_utils import set_phase


def test_list_projects_empty(client):
    response = client.get("/api/projects")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"projects": []}


def test_register_project(client, git_repo):
    response = client.post("/api/projects", json={"path": git_repo, "name": "My Repo"})
    assert response.status_code == 201
    data = response.get_json()
    assert data["name"] == "My Repo"
    assert data["path"] == git_repo
    assert "id" in data
    assert "registered" in data


def test_register_project_invalid_path(client):
    response = client.post("/api/projects", json={"path": "/nonexistent/path/abc"})
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_register_project_auto_name(client, git_repo):
    response = client.post("/api/projects", json={"path": git_repo})
    assert response.status_code == 201
    data = response.get_json()
    import os
    assert data["name"] == os.path.basename(git_repo)


def test_register_project_duplicate(client, git_repo):
    client.post("/api/projects", json={"path": git_repo, "name": "First"})
    response = client.post("/api/projects", json={"path": git_repo, "name": "Second"})
    assert response.status_code == 409
    data = response.get_json()
    assert "error" in data


def test_list_projects_after_register(client, git_repo):
    client.post("/api/projects", json={"path": git_repo, "name": "Listed Project"})
    response = client.get("/api/projects")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["projects"]) == 1
    assert data["projects"][0]["path"] == git_repo


def test_delete_project(client, project):
    response = client.delete(f"/api/projects/{project['id']}")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"ok": True}


def test_delete_project_cascades(client, workspace):
    project_id = workspace["project_id"]
    client.delete(f"/api/projects/{project_id}")
    response = client.get(f"/api/projects/{project_id}/workspaces")
    assert response.status_code == 404


def test_delete_project_removes_lsp_cache_dirs(client, project, tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))
    cache_dir = lsp_service.lsp_cache_dir(project["id"], 1)
    cache_dir.mkdir(parents=True)

    response = client.delete(f"/api/projects/{project['id']}")

    assert response.status_code == 200
    assert not cache_dir.exists()


def test_delete_project_succeeds_even_if_lsp_cache_cleanup_fails(client, project, monkeypatch):
    def _boom(project_id):
        raise OSError("cleanup exploded")

    monkeypatch.setattr(lsp_service, "remove_lsp_cache_dirs", _boom)

    response = client.delete(f"/api/projects/{project['id']}")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
