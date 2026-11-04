"""Tests for scratchpad list/read/write routes."""
from pathlib import Path

import pytest


def _create_multi_workspace(client, project, branch, **extra):
    payload = {"branch": branch, "worktree": True}
    payload.update(extra)
    return client.post(f"/api/projects/{project['id']}/workspaces", json=payload)


def test_list_scratchpads_empty_when_dir_missing(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/scratchpads")
    assert r.status_code == 200
    assert r.json["files"] == []


def test_write_then_read_roundtrip(client, workspace):
    r_write = client.put(
        "/api/ws/test-project/feature/test/scratchpads/content?name=report.md",
        json={"content": "# My Report\n\nSome details.\n"},
    )
    assert r_write.status_code == 200, r_write.json
    assert r_write.json["ok"] is True
    assert r_write.json["name"] == "report.md"
    assert r_write.json["updated_at"]

    scratchpad_file = Path(workspace["working_dir"]) / ".claude" / "scratchpad" / "report.md"
    assert scratchpad_file.exists()
    assert scratchpad_file.read_text() == "# My Report\n\nSome details.\n"

    r_read = client.get("/api/ws/test-project/feature/test/scratchpads/content?name=report.md")
    assert r_read.status_code == 200
    assert r_read.json["content"] == "# My Report\n\nSome details.\n"
    assert r_read.json["name"] == "report.md"

    r_list = client.get("/api/ws/test-project/feature/test/scratchpads")
    assert r_list.status_code == 200
    files = r_list.json["files"]
    assert len(files) == 1
    assert files[0]["name"] == "report.md"
    assert files[0]["title"] == "My Report"
    assert files[0]["size"] == len("# My Report\n\nSome details.\n")


def test_list_title_falls_back_to_prettified_filename_without_h1(client, workspace):
    scratchpad_dir = Path(workspace["working_dir"]) / ".claude" / "scratchpad"
    scratchpad_dir.mkdir(parents=True, exist_ok=True)
    (scratchpad_dir / "job-summary.md").write_text("no heading here\n")

    r = client.get("/api/ws/test-project/feature/test/scratchpads")
    assert r.status_code == 200
    files = r.json["files"]
    assert len(files) == 1
    assert files[0]["title"] == "Job Summary"


def test_read_scratchpad_not_found(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/scratchpads/content?name=missing.md")
    assert r.status_code == 404
    assert r.json["error"] == "scratchpad_not_found"


@pytest.mark.parametrize("name", ["../escape.md", "sub/dir.md", "no-extension", "report.txt"])
def test_invalid_names_rejected(client, workspace, name):
    r_read = client.get(f"/api/ws/test-project/feature/test/scratchpads/content?name={name}")
    assert r_read.status_code == 400
    assert r_read.json["error"] == "invalid_name"

    r_write = client.put(
        f"/api/ws/test-project/feature/test/scratchpads/content?name={name}",
        json={"content": "x"},
    )
    assert r_write.status_code == 400
    assert r_write.json["error"] == "invalid_name"


def test_multi_project_repo_param_scopes_to_attached_repo(client, multi_project):
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    repo_b_id = multi_project["repos"]["service-b"]["id"]
    branch = "feature/scratchpad-multi"
    r = _create_multi_workspace(client, multi_project, branch, repos=[repo_a_id, repo_b_id])
    assert r.status_code == 201, r.json

    worktree_b = Path(r.json["attached_repos"][1]["worktree_path"])
    assert worktree_b.name == "service-b"

    r_write = client.put(
        f"/api/ws/{multi_project['id']}/{branch}/scratchpads/content?name=service-b-notes.md&repo=service-b",
        json={"content": "# Service B\n"},
    )
    assert r_write.status_code == 200, r_write.json

    scratchpad_file = worktree_b / ".claude" / "scratchpad" / "service-b-notes.md"
    assert scratchpad_file.exists()
    assert scratchpad_file.read_text() == "# Service B\n"

    r_list_root = client.get(f"/api/ws/{multi_project['id']}/{branch}/scratchpads")
    assert r_list_root.status_code == 200
    assert r_list_root.json["files"] == []

    r_list_a = client.get(f"/api/ws/{multi_project['id']}/{branch}/scratchpads?repo=service-a")
    assert r_list_a.status_code == 200
    assert r_list_a.json["files"] == []

    r_list_b = client.get(f"/api/ws/{multi_project['id']}/{branch}/scratchpads?repo=service-b")
    assert r_list_b.status_code == 200
    assert [f["name"] for f in r_list_b.json["files"]] == ["service-b-notes.md"]


def test_multi_project_composite_root_scratchpad(client, multi_project):
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    branch = "feature/scratchpad-multi-root"
    r = _create_multi_workspace(client, multi_project, branch, repos=[repo_a_id])
    assert r.status_code == 201, r.json

    r_write = client.put(
        f"/api/ws/{multi_project['id']}/{branch}/scratchpads/content?name=job-summary.md",
        json={"content": "# Job Summary\n"},
    )
    assert r_write.status_code == 200, r_write.json

    r_write_dot = client.put(
        f"/api/ws/{multi_project['id']}/{branch}/scratchpads/content?name=job-summary.md&repo=.",
        json={"content": "# Job Summary\n"},
    )
    assert r_write_dot.status_code == 200, r_write_dot.json

    r_list = client.get(f"/api/ws/{multi_project['id']}/{branch}/scratchpads")
    assert r_list.status_code == 200
    assert [f["name"] for f in r_list.json["files"]] == ["job-summary.md"]

    r_list_a = client.get(f"/api/ws/{multi_project['id']}/{branch}/scratchpads?repo=service-a")
    assert r_list_a.status_code == 200
    assert r_list_a.json["files"] == []


def test_multi_project_unattached_repo_returns_repo_not_found(client, multi_project):
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    branch = "feature/scratchpad-multi-unattached"
    r = _create_multi_workspace(client, multi_project, branch, repos=[repo_a_id])
    assert r.status_code == 201, r.json

    r_list = client.get(f"/api/ws/{multi_project['id']}/{branch}/scratchpads?repo=service-c")
    assert r_list.status_code == 400
    assert r_list.json["error"] == "repo_not_found"
