"""Tests for the workspace_attach_repo / workspace_save_pr MCP tools and
the multi-repo additions to workspace_get_state.
"""


def _create_multi_workspace(client, project, branch="feature/mcp-multi", **extra):
    payload = {"branch": branch, "worktree": True}
    payload.update(extra)
    r = client.post(f"/api/projects/{project['id']}/workspaces", json=payload)
    assert r.status_code == 201, r.json
    return r.json


class TestWorkspaceAttachRepo:
    def test_attach_repo_by_rel_path_happy_path(self, client, multi_project, monkeypatch):
        ws = _create_multi_workspace(client, multi_project, branch="feature/attach-happy")
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_attach_repo

        result = workspace_attach_repo(repo="service-a")

        assert "error" not in result
        assert result["rel_path"] == "service-a"
        assert result["branch"] == "feature/attach-happy"
        assert "base_sync" in result
        assert "worktree_path" in result["instruction"] or result["worktree_path"] in result["instruction"]

    def test_attach_repo_by_name_happy_path(self, client, multi_project, monkeypatch):
        ws = _create_multi_workspace(client, multi_project, branch="feature/attach-by-name")
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_attach_repo

        result = workspace_attach_repo(repo="service-b")

        assert "error" not in result
        assert result["name"] == "service-b"

    def test_attach_repo_returns_error_when_repo_unknown(self, client, multi_project, monkeypatch):
        ws = _create_multi_workspace(client, multi_project, branch="feature/attach-unknown-mcp")
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_attach_repo

        result = workspace_attach_repo(repo="service-does-not-exist")

        assert "error" in result
        assert result["errorCategory"] == "not_found"
        assert "service-a" in str(result["valid_repos"])

    def test_attach_repo_returns_error_for_single_repo_project(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_attach_repo

        result = workspace_attach_repo(repo="anything")

        assert "error" in result
        assert result["errorCategory"] == "business"

    def test_attach_repo_returns_error_when_already_attached(self, client, multi_project, monkeypatch):
        ws = _create_multi_workspace(client, multi_project, branch="feature/attach-dup-mcp")
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_attach_repo

        first = workspace_attach_repo(repo="service-a")
        assert "error" not in first

        second = workspace_attach_repo(repo="service-a")
        assert "error" in second
        assert second["errorCategory"] == "business"


class TestWorkspaceSavePr:
    def test_save_pr_single_project_without_repo(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_pr

        result = workspace_save_pr(url="https://example.com/pr/1", title="My PR")

        assert "error" not in result
        assert result["repo_id"] is None
        assert result["url"] == "https://example.com/pr/1"

    def test_save_pr_single_project_rejects_repo(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_pr

        result = workspace_save_pr(url="https://example.com/pr/1", repo="service-a")

        assert "error" in result
        assert result["errorCategory"] == "validation"

    def test_save_pr_rejects_bad_url(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_pr

        result = workspace_save_pr(url="not-a-url")

        assert "error" in result
        assert result["errorCategory"] == "validation"

    def test_save_pr_multi_project_auto_resolves_single_attached_repo(
        self, client, multi_project, monkeypatch
    ):
        ws = _create_multi_workspace(
            client, multi_project, branch="feature/pr-auto",
            repos=[multi_project["repos"]["service-a"]["id"]],
        )
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_save_pr

        result = workspace_save_pr(url="https://example.com/pr/1")

        assert "error" not in result
        assert result["rel_path"] == "service-a"

    def test_save_pr_multi_project_requires_repo_when_ambiguous(
        self, client, multi_project, monkeypatch
    ):
        ws = _create_multi_workspace(
            client, multi_project, branch="feature/pr-ambiguous",
            repos=[
                multi_project["repos"]["service-a"]["id"],
                multi_project["repos"]["service-b"]["id"],
            ],
        )
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_save_pr

        result = workspace_save_pr(url="https://example.com/pr/1")

        assert "error" in result
        assert result["errorCategory"] == "business"

    def test_save_pr_multi_project_requires_repo_when_none_attached(
        self, client, multi_project, monkeypatch
    ):
        ws = _create_multi_workspace(client, multi_project, branch="feature/pr-none-attached")
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_save_pr

        result = workspace_save_pr(url="https://example.com/pr/1")

        assert "error" in result
        assert result["errorCategory"] == "business"

    def test_save_pr_multi_project_explicit_repo_by_name(self, client, multi_project, monkeypatch):
        ws = _create_multi_workspace(
            client, multi_project, branch="feature/pr-explicit",
            repos=[
                multi_project["repos"]["service-a"]["id"],
                multi_project["repos"]["service-b"]["id"],
            ],
        )
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_save_pr

        result = workspace_save_pr(url="https://example.com/pr/1", repo="service-b")

        assert "error" not in result
        assert result["rel_path"] == "service-b"

    def test_save_pr_multi_project_unknown_repo_name_returns_error(
        self, client, multi_project, monkeypatch
    ):
        ws = _create_multi_workspace(client, multi_project, branch="feature/pr-unknown-repo")
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_save_pr

        result = workspace_save_pr(url="https://example.com/pr/1", repo="does-not-exist")

        assert "error" in result
        assert result["errorCategory"] == "not_found"


class TestWorkspaceGetStateMultiRepo:
    def test_single_project_includes_project_type_without_repos_key(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_state

        result = workspace_get_state()

        assert result["project_type"] == "single"
        assert "repos" not in result
        assert "pull_requests" not in result

    def test_single_project_includes_pull_requests_when_present(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_state, workspace_save_pr

        workspace_save_pr(url="https://example.com/pr/1")
        result = workspace_get_state()

        assert len(result["pull_requests"]) == 1

    def test_multi_project_includes_project_type_repos_and_pull_requests(
        self, client, multi_project, monkeypatch
    ):
        ws = _create_multi_workspace(
            client, multi_project, branch="feature/state-multi",
            repos=[multi_project["repos"]["service-a"]["id"]],
        )
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import workspace_get_state

        result = workspace_get_state()

        assert result["project_type"] == "multi"
        assert "pull_requests" in result

        attached = result["repos"]["attached"]
        assert len(attached) == 1
        assert attached[0]["rel_path"] == "service-a"
        assert "git_rules" in attached[0]

        available_paths = {r["rel_path"] for r in result["repos"]["available"]}
        assert available_paths == {"service-b", "service-c"}
