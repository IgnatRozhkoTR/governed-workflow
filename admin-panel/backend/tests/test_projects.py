"""Tests for project CRUD endpoints."""
import json
import pytest

from services import lsp_service
from testing_utils import _git, set_phase


def _make_repo(base_dir, name, branch="develop"):
    repo = base_dir / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "checkout", "-b", branch)
    (repo / ".gitignore").write_text("")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Initial commit")
    return repo


@pytest.fixture
def multi_base_dir(tmp_path):
    """Base folder (not itself a repo) containing two immediate-subdir git repos."""
    base = tmp_path / "base"
    base.mkdir()
    _make_repo(base, "service-a", branch="develop")
    _make_repo(base, "service-b", branch="main")
    return base


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


def test_register_project_default_type_is_single(client, git_repo):
    response = client.post("/api/projects", json={"path": git_repo, "name": "Single"})
    assert response.status_code == 201
    assert response.get_json()["project_type"] == "single"


def test_register_project_invalid_project_type_rejected(client, git_repo):
    response = client.post("/api/projects", json={"path": git_repo, "project_type": "bogus"})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_register_multi_project_accepts_non_repo_base_dir(client, tmp_path):
    base = tmp_path / "workspace-root"
    base.mkdir()

    response = client.post(
        "/api/projects", json={"path": str(base), "name": "Multi Root", "project_type": "multi"}
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["project_type"] == "multi"
    assert not (base / ".git").exists()


def test_list_projects_includes_project_type(client, git_repo):
    client.post("/api/projects", json={"path": git_repo, "name": "Listed"})

    response = client.get("/api/projects")

    assert response.get_json()["projects"][0]["project_type"] == "single"


def test_settings_include_project_type(client, project):
    response = client.get(f"/api/projects/{project['id']}/settings")
    assert response.get_json()["project_type"] == "single"


def test_repo_scan_lists_git_subdirs(client, multi_base_dir):
    register = client.post(
        "/api/projects", json={"path": str(multi_base_dir), "name": "Multi", "project_type": "multi"}
    )
    project_id = register.get_json()["id"]

    response = client.get(f"/api/projects/{project_id}/repo-scan")

    assert response.status_code == 200
    rel_paths = [c["rel_path"] for c in response.get_json()["candidates"]]
    assert rel_paths == ["service-a", "service-b"]


def test_repo_scan_available_for_single_projects_too(client, project):
    response = client.get(f"/api/projects/{project['id']}/repo-scan")
    assert response.status_code == 200
    assert response.get_json()["candidates"] == []


def test_convert_multi_happy_path(client, multi_base_dir):
    register = client.post("/api/projects", json={"path": str(multi_base_dir), "name": "Multi"})
    project_id = register.get_json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/convert-multi",
        json={"repos": [
            {"rel_path": "service-a", "base_branch": "develop"},
            {"rel_path": "service-b", "base_branch": "main"},
        ]},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["project_type"] == "multi"
    assert [r["rel_path"] for r in data["repos"]] == ["service-a", "service-b"]

    settings = client.get(f"/api/projects/{project_id}/settings")
    assert settings.get_json()["project_type"] == "multi"


def test_convert_multi_rejects_empty_repos_list(client, multi_base_dir):
    register = client.post("/api/projects", json={"path": str(multi_base_dir), "name": "Multi"})
    project_id = register.get_json()["id"]

    response = client.post(f"/api/projects/{project_id}/convert-multi", json={"repos": []})

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_convert_multi_rejects_traversal_rel_path(client, multi_base_dir):
    register = client.post("/api/projects", json={"path": str(multi_base_dir), "name": "Multi"})
    project_id = register.get_json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/convert-multi",
        json={"repos": [{"rel_path": "../outside", "base_branch": "develop"}]},
    )

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_convert_multi_rejects_rel_path_not_in_scan_candidates(client, multi_base_dir):
    register = client.post("/api/projects", json={"path": str(multi_base_dir), "name": "Multi"})
    project_id = register.get_json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/convert-multi",
        json={"repos": [{"rel_path": "not-a-real-repo", "base_branch": "develop"}]},
    )

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_convert_multi_reconvert_updates_registry(client, multi_base_dir):
    register = client.post("/api/projects", json={"path": str(multi_base_dir), "name": "Multi"})
    project_id = register.get_json()["id"]
    client.post(
        f"/api/projects/{project_id}/convert-multi",
        json={"repos": [
            {"rel_path": "service-a", "base_branch": "develop"},
            {"rel_path": "service-b", "base_branch": "main"},
        ]},
    )

    response = client.post(
        f"/api/projects/{project_id}/convert-multi",
        json={"repos": [{"rel_path": "service-a", "base_branch": "release"}]},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert [r["rel_path"] for r in data["repos"]] == ["service-a"]
    assert data["repos"][0]["base_branch"] == "release"


def test_repos_get_put_partial_update_and_clear_override(client, multi_base_dir):
    register = client.post("/api/projects", json={"path": str(multi_base_dir), "name": "Multi"})
    project_id = register.get_json()["id"]
    client.post(
        f"/api/projects/{project_id}/convert-multi",
        json={"repos": [{"rel_path": "service-a", "base_branch": "develop"}]},
    )
    repo_id = client.get(f"/api/projects/{project_id}/repos").get_json()["repos"][0]["id"]

    get_response = client.get(f"/api/projects/{project_id}/repos/{repo_id}")
    assert get_response.status_code == 200
    assert get_response.get_json()["git_rules_override"] is None

    put_override = client.put(
        f"/api/projects/{project_id}/repos/{repo_id}",
        json={"git_rules_override": "Custom rules for service-a"},
    )
    assert put_override.status_code == 200
    assert put_override.get_json()["git_rules_override"] == "Custom rules for service-a"
    assert put_override.get_json()["base_branch"] == "develop"

    put_base_only = client.put(
        f"/api/projects/{project_id}/repos/{repo_id}", json={"base_branch": "release"}
    )
    assert put_base_only.status_code == 200
    assert put_base_only.get_json()["base_branch"] == "release"
    assert put_base_only.get_json()["git_rules_override"] == "Custom rules for service-a"

    put_clear = client.put(
        f"/api/projects/{project_id}/repos/{repo_id}", json={"git_rules_override": None}
    )
    assert put_clear.status_code == 200
    assert put_clear.get_json()["git_rules_override"] is None


def test_repos_put_empty_body_rejected(client, multi_base_dir):
    register = client.post("/api/projects", json={"path": str(multi_base_dir), "name": "Multi"})
    project_id = register.get_json()["id"]
    client.post(
        f"/api/projects/{project_id}/convert-multi",
        json={"repos": [{"rel_path": "service-a", "base_branch": "develop"}]},
    )
    repo_id = client.get(f"/api/projects/{project_id}/repos").get_json()["repos"][0]["id"]

    response = client.put(f"/api/projects/{project_id}/repos/{repo_id}", json={})

    assert response.status_code == 400


def test_repos_get_404_for_unknown_repo(client, project):
    response = client.get(f"/api/projects/{project['id']}/repos/99999")
    assert response.status_code == 404


def test_repos_get_404_for_repo_belonging_to_different_project(client, multi_base_dir, project):
    register = client.post("/api/projects", json={"path": str(multi_base_dir), "name": "Multi"})
    other_project_id = register.get_json()["id"]
    client.post(
        f"/api/projects/{other_project_id}/convert-multi",
        json={"repos": [{"rel_path": "service-a", "base_branch": "develop"}]},
    )
    repo_id = client.get(f"/api/projects/{other_project_id}/repos").get_json()["repos"][0]["id"]

    response = client.get(f"/api/projects/{project['id']}/repos/{repo_id}")

    assert response.status_code == 404
