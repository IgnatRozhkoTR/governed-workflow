"""Integration tests for multi-repo workspace lifecycle, repo attach, and PR endpoints."""
import subprocess
from pathlib import Path

from testing_utils import _git, GIT_ENV


def _create_multi_workspace(client, project, branch="feature/multi", **extra):
    payload = {"branch": branch, "worktree": True}
    payload.update(extra)
    return client.post(f"/api/projects/{project['id']}/workspaces", json=payload)


# ─── CREATION ──────────────────────────────────────────────────────────────


def test_create_multi_workspace_creates_plain_composite_dir(client, multi_project):
    r = _create_multi_workspace(client, multi_project)
    assert r.status_code == 201, r.json

    composite = Path(multi_project["path"]) / ".claude" / "worktrees" / "feature-multi"
    assert composite.is_dir()
    assert not (composite / ".git").exists()
    assert r.json["working_dir"] == str(composite)


def test_create_multi_workspace_installs_configs(client, multi_project):
    r = _create_multi_workspace(client, multi_project, branch="feature/multi-cfg")
    assert r.status_code == 201, r.json

    composite = Path(r.json["working_dir"])
    assert (composite / ".claude" / "settings.json").exists()
    assert (composite / "CLAUDE.md").exists()


def test_create_multi_workspace_does_not_touch_base_dir_git_state(client, multi_project):
    base = Path(multi_project["path"])
    r = _create_multi_workspace(client, multi_project, branch="feature/multi-nogit")
    assert r.status_code == 201, r.json
    assert not (base / ".git").exists()
    assert "base_sync" not in r.json


def test_create_multi_workspace_rejects_worktree_false(client, multi_project):
    r = client.post(
        f"/api/projects/{multi_project['id']}/workspaces",
        json={"branch": "feature/no-wt", "worktree": False},
    )
    assert r.status_code == 400


def test_create_multi_workspace_skips_lsp_prewarm(client, multi_project):
    r = _create_multi_workspace(client, multi_project, branch="feature/multi-lsp")
    assert r.status_code == 201, r.json
    assert r.json["lsp_prewarm"]["skipped_reason"] == "multi_project"


def test_create_multi_workspace_with_repos_list_attaches_and_returns_results(client, multi_project):
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    repo_b_id = multi_project["repos"]["service-b"]["id"]

    r = _create_multi_workspace(
        client, multi_project, branch="feature/multi-attach", repos=[repo_a_id, repo_b_id]
    )
    assert r.status_code == 201, r.json

    attached = r.json["attached_repos"]
    assert len(attached) == 2
    by_rel = {a["rel_path"]: a for a in attached}
    assert "service-a" in by_rel
    assert "service-b" in by_rel
    assert "base_sync" in by_rel["service-a"]
    assert by_rel["service-a"]["branch"] == "feature/multi-attach"

    worktree_a = Path(multi_project["path"]) / ".claude" / "worktrees" / "feature-multi-attach" / "service-a"
    assert worktree_a.is_dir()


def test_create_multi_workspace_repos_list_failed_attach_does_not_roll_back(client, multi_project):
    r = _create_multi_workspace(
        client, multi_project, branch="feature/multi-bad-repo", repos=[999999]
    )
    assert r.status_code == 201, r.json
    assert r.json["attached_repos"][0]["error"]

    ws_check = client.get(f"/api/ws/{multi_project['id']}/feature/multi-bad-repo/repo-state")
    assert ws_check.status_code == 200


# ─── ATTACH ENDPOINT ───────────────────────────────────────────────────────


def test_attach_repo_endpoint_creates_worktree_on_ticket_branch(client, multi_project):
    _create_multi_workspace(client, multi_project, branch="feature/attach-ep")
    repo_id = multi_project["repos"]["service-b"]["id"]

    r = client.post(
        f"/api/ws/{multi_project['id']}/feature/attach-ep/repos/attach",
        json={"repo_id": repo_id},
    )
    assert r.status_code == 200, r.json
    assert r.json["attached"]["rel_path"] == "service-b"
    assert r.json["attached"]["branch"] == "feature/attach-ep"
    assert "base_sync" in r.json

    worktree = Path(r.json["attached"]["worktree_path"])
    assert worktree.is_dir()
    _git(worktree, "rev-parse", "--verify", f"refs/heads/{r.json['attached']['branch']}")


def test_attach_repo_twice_returns_400(client, multi_project):
    _create_multi_workspace(client, multi_project, branch="feature/attach-twice")
    repo_id = multi_project["repos"]["service-b"]["id"]

    first = client.post(
        f"/api/ws/{multi_project['id']}/feature/attach-twice/repos/attach",
        json={"repo_id": repo_id},
    )
    assert first.status_code == 200, first.json

    second = client.post(
        f"/api/ws/{multi_project['id']}/feature/attach-twice/repos/attach",
        json={"repo_id": repo_id},
    )
    assert second.status_code == 400


def test_attach_unknown_repo_returns_400(client, multi_project):
    _create_multi_workspace(client, multi_project, branch="feature/attach-unknown")

    r = client.post(
        f"/api/ws/{multi_project['id']}/feature/attach-unknown/repos/attach",
        json={"repo_id": 999999},
    )
    assert r.status_code == 400


def test_attach_disabled_repo_returns_400(client, multi_project):
    from core.db import get_db

    repo_id = multi_project["repos"]["service-c"]["id"]
    db = get_db()
    try:
        db.execute("UPDATE project_repos SET enabled = 0 WHERE id = ?", (repo_id,))
        db.commit()
    finally:
        db.close()

    _create_multi_workspace(client, multi_project, branch="feature/attach-disabled")

    r = client.post(
        f"/api/ws/{multi_project['id']}/feature/attach-disabled/repos/attach",
        json={"repo_id": repo_id},
    )
    assert r.status_code == 400


def test_attach_repo_endpoint_rejects_single_repo_project(client, workspace, project):
    r = client.post(
        f"/api/ws/{project['id']}/feature/test/repos/attach",
        json={"repo_id": 1},
    )
    assert r.status_code == 400


def test_reattach_after_archive_reuses_existing_branch(client, multi_project):
    branch = "feature/reattach"
    sanitized = "feature-reattach"
    repo_id = multi_project["repos"]["service-b"]["id"]

    _create_multi_workspace(client, multi_project, branch=branch)
    attach1 = client.post(
        f"/api/ws/{multi_project['id']}/{branch}/repos/attach", json={"repo_id": repo_id}
    )
    assert attach1.status_code == 200, attach1.json

    archive = client.put(f"/api/ws/{multi_project['id']}/{branch}/archive")
    assert archive.status_code == 200

    repo_abs = Path(multi_project["path"]) / "service-b"
    _git(repo_abs, "rev-parse", "--verify", f"refs/heads/{branch}")

    r2 = _create_multi_workspace(client, multi_project, branch=branch)
    assert r2.status_code == 201, r2.json

    attach2 = client.post(
        f"/api/ws/{multi_project['id']}/{branch}/repos/attach", json={"repo_id": repo_id}
    )
    assert attach2.status_code == 200, attach2.json
    worktree2 = Path(attach2.json["attached"]["worktree_path"])
    assert worktree2.is_dir()


# ─── ATTACH MERGE LAYER ─────────────────────────────────────────────────────


def test_attach_repo_worktree_gets_concatenated_claude_md(client, multi_project):
    (Path(multi_project["path"]) / "CLAUDE.md").write_text("PROJECT_WIDE_CLAUDE_MD_MARKER")

    _create_multi_workspace(client, multi_project, branch="feature/attach-claude-md")
    repo_id = multi_project["repos"]["service-b"]["id"]

    r = client.post(
        f"/api/ws/{multi_project['id']}/feature/attach-claude-md/repos/attach",
        json={"repo_id": repo_id},
    )
    assert r.status_code == 200, r.json

    worktree = Path(r.json["attached"]["worktree_path"])
    claude_md = worktree / "CLAUDE.md"
    assert claude_md.is_file()
    assert not claude_md.is_symlink()
    content = claude_md.read_text()
    assert "PROJECT_WIDE_CLAUDE_MD_MARKER" in content
    assert "Governed Workflow Defaults" in content


def test_attach_repo_worktree_rules_resolve_to_project_default_without_override(client, multi_project):
    project_rules = Path(multi_project["path"]) / ".claude" / "git-rules.md"
    project_rules.parent.mkdir(parents=True, exist_ok=True)
    project_rules.write_text("PROJECT_DEFAULT_GIT_RULES")

    _create_multi_workspace(client, multi_project, branch="feature/attach-rules-default")
    repo_id = multi_project["repos"]["service-b"]["id"]

    r = client.post(
        f"/api/ws/{multi_project['id']}/feature/attach-rules-default/repos/attach",
        json={"repo_id": repo_id},
    )
    assert r.status_code == 200, r.json

    worktree = Path(r.json["attached"]["worktree_path"])
    rules_file = worktree / ".claude" / "git-rules.md"
    assert rules_file.is_file()
    assert rules_file.read_text() == "PROJECT_DEFAULT_GIT_RULES"


def test_attach_repo_worktree_rules_use_per_repo_override(client, multi_project):
    from core.db import get_db
    from services import repo_service

    project_rules = Path(multi_project["path"]) / ".claude" / "git-rules.md"
    project_rules.parent.mkdir(parents=True, exist_ok=True)
    project_rules.write_text("PROJECT_DEFAULT_GIT_RULES")

    repo_a_id = multi_project["repos"]["service-a"]["id"]
    repo_b_id = multi_project["repos"]["service-b"]["id"]

    db = get_db()
    try:
        repo_service.update_repo(
            db, multi_project["id"], repo_a_id, git_rules_override="SERVICE_A_SPECIFIC_RULES"
        )
    finally:
        db.close()

    _create_multi_workspace(
        client, multi_project, branch="feature/attach-rules-override",
        repos=[repo_a_id, repo_b_id],
    )

    a_rules = (
        Path(multi_project["path"]) / ".claude" / "worktrees" / "feature-attach-rules-override"
        / "service-a" / ".claude" / "git-rules.md"
    )
    b_rules = (
        Path(multi_project["path"]) / ".claude" / "worktrees" / "feature-attach-rules-override"
        / "service-b" / ".claude" / "git-rules.md"
    )
    assert a_rules.read_text() == "SERVICE_A_SPECIFIC_RULES"
    assert b_rules.read_text() == "PROJECT_DEFAULT_GIT_RULES"
    assert not a_rules.is_symlink()
    assert not b_rules.is_symlink()


def test_attach_repo_installs_git_hooks(client, multi_project):
    _create_multi_workspace(client, multi_project, branch="feature/attach-hooks")
    repo_id = multi_project["repos"]["service-b"]["id"]

    r = client.post(
        f"/api/ws/{multi_project['id']}/feature/attach-hooks/repos/attach",
        json={"repo_id": repo_id},
    )
    assert r.status_code == 200, r.json

    worktree = Path(r.json["attached"]["worktree_path"])
    hooks_dir = worktree / ".claude" / "git-hooks"
    assert (hooks_dir / "pre-commit").is_file()
    assert (hooks_dir / "pre-push").is_file()

    result = subprocess.run(
        ["git", "config", "--worktree", "core.hooksPath"],
        cwd=str(worktree), capture_output=True, text=True, env=GIT_ENV,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == str(hooks_dir)


def test_attach_two_repos_same_request_does_not_error_or_duplicate_write(client, multi_project):
    (Path(multi_project["path"]) / "CLAUDE.md").write_text("SHARED_PROJECT_CLAUDE_MD")
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    repo_b_id = multi_project["repos"]["service-b"]["id"]

    r = _create_multi_workspace(
        client, multi_project, branch="feature/attach-two-repos", repos=[repo_a_id, repo_b_id]
    )
    assert r.status_code == 201, r.json
    assert all("error" not in entry for entry in r.json["attached_repos"])

    composite = Path(r.json["working_dir"])
    for rel_path in ("service-a", "service-b"):
        claude_md = composite / rel_path / "CLAUDE.md"
        assert claude_md.is_file()
        assert "SHARED_PROJECT_CLAUDE_MD" in claude_md.read_text()

    project_claude_md = Path(multi_project["path"]) / "CLAUDE.md"
    assert project_claude_md.read_text() == "SHARED_PROJECT_CLAUDE_MD"


# ─── ARCHIVE ───────────────────────────────────────────────────────────────


def test_archive_multi_workspace_removes_worktrees_and_composite_dir_keeps_branches(
    client, multi_project
):
    branch = "feature/archive-multi"
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    repo_b_id = multi_project["repos"]["service-b"]["id"]

    _create_multi_workspace(client, multi_project, branch=branch, repos=[repo_a_id, repo_b_id])

    composite = Path(multi_project["path"]) / ".claude" / "worktrees" / "feature-archive-multi"
    assert composite.exists()

    r = client.put(f"/api/ws/{multi_project['id']}/{branch}/archive")
    assert r.status_code == 200, r.json

    assert not composite.exists()

    for rel_path in ("service-a", "service-b"):
        repo_abs = Path(multi_project["path"]) / rel_path
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
            cwd=str(repo_abs), capture_output=True, text=True, env=GIT_ENV,
        )
        assert result.returncode == 0, f"branch should survive archive in {rel_path}"


# ─── REPO-STATE ENDPOINT ───────────────────────────────────────────────────


def test_repo_state_single_project_returns_empty_shapes(client, workspace, project):
    r = client.get(f"/api/ws/{project['id']}/feature/test/repo-state")
    assert r.status_code == 200
    assert r.json == {"project_type": "single", "attached": [], "available": []}


def test_repo_state_multi_project_shape(client, multi_project):
    branch = "feature/repo-state"
    repo_a_id = multi_project["repos"]["service-a"]["id"]

    _create_multi_workspace(client, multi_project, branch=branch, repos=[repo_a_id])

    r = client.get(f"/api/ws/{multi_project['id']}/{branch}/repo-state")
    assert r.status_code == 200, r.json
    assert r.json["project_type"] == "multi"

    attached = r.json["attached"]
    assert len(attached) == 1
    assert attached[0]["rel_path"] == "service-a"
    assert attached[0]["pr"] is None

    available_paths = {a["rel_path"] for a in r.json["available"]}
    assert available_paths == {"service-b", "service-c"}


def test_repo_state_reflects_saved_pr(client, multi_project):
    branch = "feature/repo-state-pr"
    repo_a_id = multi_project["repos"]["service-a"]["id"]

    _create_multi_workspace(client, multi_project, branch=branch, repos=[repo_a_id])
    client.post(
        f"/api/ws/{multi_project['id']}/{branch}/prs",
        json={"url": "https://example.com/pr/1", "repo_id": repo_a_id, "title": "My PR"},
    )

    r = client.get(f"/api/ws/{multi_project['id']}/{branch}/repo-state")
    assert r.status_code == 200
    assert r.json["attached"][0]["pr"]["url"] == "https://example.com/pr/1"


# ─── PR ENDPOINTS ──────────────────────────────────────────────────────────


def test_prs_get_empty_for_new_workspace(client, workspace, project):
    r = client.get(f"/api/ws/{project['id']}/feature/test/prs")
    assert r.status_code == 200
    assert r.json == {"prs": []}


def test_prs_post_creates_project_wide_pr(client, workspace, project):
    r = client.post(
        f"/api/ws/{project['id']}/feature/test/prs",
        json={"url": "https://example.com/pr/1", "title": "My PR"},
    )
    assert r.status_code == 200, r.json
    assert r.json["url"] == "https://example.com/pr/1"
    assert r.json["repo_id"] is None

    listed = client.get(f"/api/ws/{project['id']}/feature/test/prs")
    assert len(listed.json["prs"]) == 1


def test_prs_post_rejects_invalid_url(client, workspace, project):
    r = client.post(
        f"/api/ws/{project['id']}/feature/test/prs",
        json={"url": "not-a-url"},
    )
    assert r.status_code == 400


def test_prs_post_validates_repo_id(client, multi_project):
    branch = "feature/prs-repo-id"
    _create_multi_workspace(client, multi_project, branch=branch)

    r = client.post(
        f"/api/ws/{multi_project['id']}/{branch}/prs",
        json={"url": "https://example.com/pr/1", "repo_id": 999999},
    )
    assert r.status_code == 400


def test_prs_post_accepts_registered_repo_id_for_multi(client, multi_project):
    branch = "feature/prs-valid-repo"
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    _create_multi_workspace(client, multi_project, branch=branch)

    r = client.post(
        f"/api/ws/{multi_project['id']}/{branch}/prs",
        json={"url": "https://example.com/pr/1", "repo_id": repo_a_id},
    )
    assert r.status_code == 200, r.json
    assert r.json["repo_id"] == repo_a_id
    assert r.json["rel_path"] == "service-a"


def test_prs_delete_removes_row(client, workspace, project):
    created = client.post(
        f"/api/ws/{project['id']}/feature/test/prs",
        json={"url": "https://example.com/pr/1"},
    ).json

    r = client.delete(f"/api/ws/{project['id']}/feature/test/prs/{created['id']}")
    assert r.status_code == 200

    listed = client.get(f"/api/ws/{project['id']}/feature/test/prs")
    assert listed.json["prs"] == []


def test_prs_delete_returns_404_for_unknown_id(client, workspace, project):
    r = client.delete(f"/api/ws/{project['id']}/feature/test/prs/999999")
    assert r.status_code == 404
