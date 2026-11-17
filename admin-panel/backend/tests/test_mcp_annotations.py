"""Tests for the workspace_*annotation* MCP tools."""
from pathlib import Path

import pytest

from testing_utils import _git

FILE = "src/app.py"
ORIGINAL = "".join(f"line {n}\n" for n in range(1, 11))


@pytest.fixture
def in_workspace(workspace, git_repo, monkeypatch):
    repo = Path(git_repo)
    (repo / "src").mkdir()
    (repo / FILE).write_text(ORIGINAL)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Add app")
    monkeypatch.chdir(git_repo)
    return repo


def _annotate(**overrides):
    from mcp_server import workspace_annotate
    params = {"file_path": FILE, "line_start": 3, "line_end": 4, "text": "Why"}
    params.update(overrides)
    return workspace_annotate(**params)


def _assert_error(result, category, code):
    assert (result["errorCategory"], result["isRetryable"], result["code"], bool(result["error"])) == (
        category, False, code, True)


class TestWorkspaceAnnotate:
    def test_annotate_should_return_created_annotation(self, in_workspace):
        result = _annotate()

        assert (result["file_path"], result["line_start"], result["line_end"], result["text"], result["stale"]) == (
            FILE, 3, 4, "Why", False)

    def test_annotate_should_default_author_to_agent(self, in_workspace):
        assert _annotate()["author"] == "agent"

    def test_annotate_should_store_explicit_author(self, in_workspace):
        assert _annotate(author="middle-backend-engineer")["author"] == "middle-backend-engineer"

    def test_annotate_should_fall_back_to_agent_when_author_blank(self, in_workspace):
        assert _annotate(author="   ")["author"] == "agent"

    def test_annotate_should_persist_after_call(self, in_workspace):
        from mcp_server import workspace_list_annotations
        created = _annotate()

        assert [a["id"] for a in workspace_list_annotations()] == [created["id"]]

    def test_annotate_should_return_validation_envelope_when_range_invalid(self, in_workspace):
        _assert_error(_annotate(line_end=20), "validation", "invalid_line_range")

    def test_annotate_should_return_not_found_envelope_when_file_missing(self, in_workspace):
        _assert_error(_annotate(file_path="missing.py"), "not_found", "file_not_found")

    def test_annotate_should_return_error_when_no_workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = _annotate()

        assert result["errorCategory"] == "not_found"


class TestWorkspaceUpdateAnnotation:
    def test_update_should_change_text(self, in_workspace):
        from mcp_server import workspace_update_annotation
        created = _annotate()

        result = workspace_update_annotation(id=created["id"], text="Revised")

        assert (result["text"], result["line_start"]) == ("Revised", 3)

    def test_update_should_move_range(self, in_workspace):
        from mcp_server import workspace_update_annotation
        created = _annotate()

        result = workspace_update_annotation(id=created["id"], line_start=1, line_end=2)

        assert (result["line_start"], result["line_end"]) == (1, 2)

    def test_update_should_return_validation_envelope_when_nothing_given(self, in_workspace):
        from mcp_server import workspace_update_annotation
        created = _annotate()

        _assert_error(workspace_update_annotation(id=created["id"]), "validation", "nothing_to_update")

    def test_update_should_return_not_found_envelope_when_id_unknown(self, in_workspace):
        from mcp_server import workspace_update_annotation

        _assert_error(workspace_update_annotation(id=999999, text="x"), "not_found", "not_found")


class TestWorkspaceDeleteAnnotation:
    def test_delete_should_return_ok_and_remove(self, in_workspace):
        from mcp_server import workspace_delete_annotation, workspace_list_annotations
        created = _annotate()

        result = workspace_delete_annotation(id=created["id"])

        assert (result, workspace_list_annotations()) == ({"ok": True, "id": created["id"]}, [])

    def test_delete_should_return_not_found_envelope_when_id_unknown(self, in_workspace):
        from mcp_server import workspace_delete_annotation

        _assert_error(workspace_delete_annotation(id=999999), "not_found", "not_found")


class TestWorkspaceListAnnotations:
    def test_list_without_file_should_return_stored_lines(self, in_workspace):
        from mcp_server import workspace_list_annotations
        _annotate()
        (in_workspace / FILE).write_text("x\n")

        [annotation] = workspace_list_annotations()

        assert (annotation["line_start"], annotation["stale"]) == (3, False)

    def test_list_with_file_should_reanchor_against_working_tree(self, in_workspace):
        from mcp_server import workspace_list_annotations
        _annotate()
        (in_workspace / FILE).write_text("top\n" + ORIGINAL)

        [annotation] = workspace_list_annotations(file_path=FILE)

        assert (annotation["line_start"], annotation["line_end"], annotation["stale"]) == (4, 5, False)

    def test_list_with_file_should_return_single_element_error_list_when_path_invalid(self, in_workspace):
        from mcp_server import workspace_list_annotations

        result = workspace_list_annotations(file_path="../x.py")

        assert len(result) == 1
        _assert_error(result[0], "validation", "invalid_file_path")

    def test_list_should_return_error_list_when_no_workspace(self, tmp_path, monkeypatch):
        from mcp_server import workspace_list_annotations
        monkeypatch.chdir(tmp_path)

        result = workspace_list_annotations()

        assert result[0]["errorCategory"] == "not_found"
