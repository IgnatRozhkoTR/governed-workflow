"""Tests for services/scratchpad_service.py and the scratchpad_* MCP tools."""
from pathlib import Path

import pytest

from services import scratchpad_service
from services.scratchpad_service import ScratchpadServiceError


def _create_multi_workspace(client, project, branch, **extra):
    payload = {"branch": branch, "worktree": True}
    payload.update(extra)
    r = client.post(f"/api/projects/{project['id']}/workspaces", json=payload)
    assert r.status_code == 201, r.json
    return r.json


class TestScratchpadServiceCrud:
    def test_create_scratchpad_writes_file(self, tmp_path):
        result = scratchpad_service.create_scratchpad(tmp_path, "report.md", "# Report\nbody\n")
        assert result["name"] == "report.md"
        assert result["title"] == "Report"
        assert (tmp_path / "report.md").read_text() == "# Report\nbody\n"

    def test_create_scratchpad_fails_when_already_exists(self, tmp_path):
        scratchpad_service.create_scratchpad(tmp_path, "report.md", "# Report\n")
        with pytest.raises(ScratchpadServiceError) as exc_info:
            scratchpad_service.create_scratchpad(tmp_path, "report.md", "# Again\n")
        assert exc_info.value.code == "already_exists"

    def test_replace_scratchpad_overwrites_content(self, tmp_path):
        scratchpad_service.create_scratchpad(tmp_path, "report.md", "# Report\nold\n")
        scratchpad_service.replace_scratchpad(tmp_path, "report.md", "# Report\nnew\n")
        assert (tmp_path / "report.md").read_text() == "# Report\nnew\n"

    def test_replace_scratchpad_fails_when_missing(self, tmp_path):
        with pytest.raises(ScratchpadServiceError) as exc_info:
            scratchpad_service.replace_scratchpad(tmp_path, "missing.md", "# X\n")
        assert exc_info.value.code == "not_found"

    def test_patch_scratchpad_replaces_single_occurrence(self, tmp_path):
        scratchpad_service.create_scratchpad(tmp_path, "report.md", "# Report\nfoo bar\n")
        scratchpad_service.patch_scratchpad(tmp_path, "report.md", "foo", "baz")
        assert (tmp_path / "report.md").read_text() == "# Report\nbaz bar\n"

    def test_patch_scratchpad_fails_when_no_match(self, tmp_path):
        scratchpad_service.create_scratchpad(tmp_path, "report.md", "# Report\nfoo\n")
        with pytest.raises(ScratchpadServiceError) as exc_info:
            scratchpad_service.patch_scratchpad(tmp_path, "report.md", "missing", "x")
        assert exc_info.value.code == "no_match"

    def test_patch_scratchpad_fails_when_ambiguous(self, tmp_path):
        scratchpad_service.create_scratchpad(tmp_path, "report.md", "# Report\nfoo foo\n")
        with pytest.raises(ScratchpadServiceError) as exc_info:
            scratchpad_service.patch_scratchpad(tmp_path, "report.md", "foo", "x")
        assert exc_info.value.code == "ambiguous_match"

    def test_delete_scratchpad_removes_file(self, tmp_path):
        scratchpad_service.create_scratchpad(tmp_path, "report.md", "# Report\n")
        scratchpad_service.delete_scratchpad(tmp_path, "report.md")
        assert not (tmp_path / "report.md").exists()

    def test_delete_scratchpad_fails_when_missing(self, tmp_path):
        with pytest.raises(ScratchpadServiceError) as exc_info:
            scratchpad_service.delete_scratchpad(tmp_path, "missing.md")
        assert exc_info.value.code == "not_found"

    @pytest.mark.parametrize("name", ["../escape.md", "sub/dir.md", "no-extension", "report.txt", ""])
    def test_validate_name_rejects_unsafe_or_malformed_names(self, name):
        assert scratchpad_service.validate_name(name) == "invalid_name"

    def test_normalize_name_appends_md_extension(self):
        assert scratchpad_service.normalize_name("report") == "report.md"
        assert scratchpad_service.normalize_name("report.md") == "report.md"


class TestScratchpadMcpTools:
    def test_scratchpad_create_happy_path(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_create

        result = scratchpad_create(name="job-summary", content="# Job Summary\nAll done.\n")

        assert "error" not in result
        assert result["name"] == "job-summary.md"
        assert result["title"] == "Job Summary"
        scratchpad_file = Path(workspace["working_dir"]) / ".claude" / "scratchpad" / "job-summary.md"
        assert scratchpad_file.read_text() == "# Job Summary\nAll done.\n"

    def test_scratchpad_create_fails_when_already_exists(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_create

        scratchpad_create(name="job-summary", content="# Job Summary\n")
        result = scratchpad_create(name="job-summary", content="# Again\n")

        assert result["errorCategory"] == "business"

    def test_scratchpad_replace_happy_path(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_create, scratchpad_replace

        scratchpad_create(name="job-summary", content="# Job Summary\nold\n")
        result = scratchpad_replace(name="job-summary", content="# Job Summary\nnew\n")

        assert "error" not in result
        scratchpad_file = Path(workspace["working_dir"]) / ".claude" / "scratchpad" / "job-summary.md"
        assert scratchpad_file.read_text() == "# Job Summary\nnew\n"

    def test_scratchpad_replace_fails_when_missing(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_replace

        result = scratchpad_replace(name="missing", content="# X\n")

        assert result["errorCategory"] == "not_found"

    def test_scratchpad_patch_single_occurrence(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_create, scratchpad_patch

        scratchpad_create(name="job-summary", content="# Job Summary\nfoo bar\n")
        result = scratchpad_patch(name="job-summary", old_string="foo", new_string="baz")

        assert "error" not in result
        scratchpad_file = Path(workspace["working_dir"]) / ".claude" / "scratchpad" / "job-summary.md"
        assert scratchpad_file.read_text() == "# Job Summary\nbaz bar\n"

    def test_scratchpad_patch_fails_when_no_match(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_create, scratchpad_patch

        scratchpad_create(name="job-summary", content="# Job Summary\nfoo\n")
        result = scratchpad_patch(name="job-summary", old_string="missing", new_string="x")

        assert result["errorCategory"] == "business"

    def test_scratchpad_patch_fails_when_ambiguous(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_create, scratchpad_patch

        scratchpad_create(name="job-summary", content="# Job Summary\nfoo foo\n")
        result = scratchpad_patch(name="job-summary", old_string="foo", new_string="x")

        assert result["errorCategory"] == "business"

    def test_scratchpad_delete_happy_path(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_create, scratchpad_delete

        scratchpad_create(name="job-summary", content="# Job Summary\n")
        result = scratchpad_delete(name="job-summary")

        assert result == {"ok": True, "name": "job-summary.md"}
        scratchpad_file = Path(workspace["working_dir"]) / ".claude" / "scratchpad" / "job-summary.md"
        assert not scratchpad_file.exists()

    def test_scratchpad_delete_fails_when_missing(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_delete

        result = scratchpad_delete(name="missing")

        assert result["errorCategory"] == "not_found"

    @pytest.mark.parametrize("name", ["../escape", "sub/dir.md"])
    def test_scratchpad_create_rejects_path_traversal(self, workspace, monkeypatch, name):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import scratchpad_create

        result = scratchpad_create(name=name, content="# X\n")

        assert result["errorCategory"] == "validation"

    def test_scratchpad_create_scopes_to_attached_repo(self, client, multi_project, monkeypatch):
        repo_a_id = multi_project["repos"]["service-a"]["id"]
        branch = "feature/scratchpad-mcp-multi"
        ws = _create_multi_workspace(client, multi_project, branch, repos=[repo_a_id])
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import scratchpad_create

        result = scratchpad_create(name="notes", content="# Notes\n", repo="service-a")

        assert "error" not in result
        repo_worktree = Path(ws["attached_repos"][0]["worktree_path"])
        scratchpad_file = repo_worktree / ".claude" / "scratchpad" / "notes.md"
        assert scratchpad_file.exists()

    def test_scratchpad_create_returns_not_found_for_unattached_repo(self, client, multi_project, monkeypatch):
        repo_a_id = multi_project["repos"]["service-a"]["id"]
        branch = "feature/scratchpad-mcp-unattached"
        ws = _create_multi_workspace(client, multi_project, branch, repos=[repo_a_id])
        monkeypatch.chdir(ws["working_dir"])
        from mcp_server import scratchpad_create

        result = scratchpad_create(name="notes", content="# Notes\n", repo="service-c")

        assert result["errorCategory"] == "not_found"
