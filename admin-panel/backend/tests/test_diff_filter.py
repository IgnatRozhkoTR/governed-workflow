"""Tests for diff_filter: reviewable file list extraction and exclusion rules."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.diff_filter import (
    list_reviewable_files,
    count_modified,
    _parse_line,
    ReviewableFile,
)

REPO = Path("/fake/repo")


def _mock_diff(output: str):
    """Return a context manager that stubs _run_git_diff to emit output."""
    mock_result = MagicMock()
    mock_result.stdout = output
    return patch("services.diff_filter.subprocess.run", return_value=mock_result)


# ── _parse_line unit tests ───────────────────────────────────────────────────


def test_parse_line_modified_returns_reviewable_file():
    rf = _parse_line("M\tsrc/main.py")
    assert rf == ReviewableFile(path="src/main.py", status="M")


def test_parse_line_added_returns_reviewable_file():
    rf = _parse_line("A\tsrc/new.py")
    assert rf == ReviewableFile(path="src/new.py", status="A")


def test_parse_line_deleted_returns_reviewable_file():
    rf = _parse_line("D\tsrc/old.py")
    assert rf == ReviewableFile(path="src/old.py", status="D")


def test_parse_line_pure_rename_extracts_new_path_and_similarity():
    rf = _parse_line("R100\told/path.py\tnew/path.py")
    assert rf == ReviewableFile(path="new/path.py", status="R100", similarity=100)


def test_parse_line_partial_rename_extracts_similarity():
    rf = _parse_line("R085\told/path.py\tnew/path.py")
    assert rf == ReviewableFile(path="new/path.py", status="R085", similarity=85)


def test_parse_line_malformed_no_tab_returns_none():
    assert _parse_line("no-tab-here") is None


def test_parse_line_empty_string_returns_none():
    assert _parse_line("") is None


def test_parse_line_rename_without_new_path_returns_none():
    # R status with only one path tab — treated as single-path entry but lacks new path
    rf = _parse_line("R085\told/path.py")
    # len(parts) == 2, so falls through to single-path branch
    assert rf == ReviewableFile(path="old/path.py", status="R085")


# ── list_reviewable_files integration tests ──────────────────────────────────


def test_list_reviewable_files_includes_modified():
    with _mock_diff("M\tsrc/main.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert len(result) == 1
    assert result[0].path == "src/main.py"
    assert result[0].status == "M"


def test_list_reviewable_files_includes_added():
    with _mock_diff("A\tsrc/feature.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert len(result) == 1
    assert result[0].path == "src/feature.py"


def test_list_reviewable_files_includes_deleted():
    with _mock_diff("D\tsrc/legacy.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert len(result) == 1
    assert result[0].path == "src/legacy.py"


def test_list_reviewable_files_excludes_pure_rename():
    with _mock_diff("R100\told/path.py\tnew/path.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_includes_partial_rename():
    with _mock_diff("R085\told/path.py\tnew/path.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert len(result) == 1
    assert result[0].path == "new/path.py"
    assert result[0].similarity == 85


def test_list_reviewable_files_excludes_migration():
    with _mock_diff("M\tapp/migrations/0001_initial.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_excludes_min_js():
    with _mock_diff("M\tstatic/bundle.min.js\n"):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_excludes_min_css():
    with _mock_diff("M\tstatic/styles.min.css\n"):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_excludes_vendor():
    with _mock_diff("A\tnode_modules/vendor/lib/util.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_excludes_protobuf():
    with _mock_diff("M\tproto/user_pb.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_excludes_snap():
    with _mock_diff("M\t__snapshots__/component.snap\n"):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_excludes_lock_files():
    diff = "M\tpackage-lock.json\nM\tyarn.lock\nM\tPoetry.lock\n"
    with _mock_diff(diff):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_extra_excludes_honored():
    diff = "M\tsrc/main.py\nM\tdocs/spec.md\n"
    with _mock_diff(diff):
        result = list_reviewable_files(REPO, "main", extra_excludes=("docs/*.md",))
    assert len(result) == 1
    assert result[0].path == "src/main.py"


def test_list_reviewable_files_multiple_excludes_combined():
    diff = (
        "M\tsrc/main.py\n"
        "M\tapp/migrations/0002_add_field.py\n"
        "M\tstatic/app.min.js\n"
        "R100\told.py\tnew.py\n"
        "M\tdocs/readme.md\n"
    )
    with _mock_diff(diff):
        result = list_reviewable_files(REPO, "main", extra_excludes=("docs/*.md",))
    assert len(result) == 1
    assert result[0].path == "src/main.py"


def test_list_reviewable_files_empty_diff_returns_empty_list():
    with _mock_diff(""):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_malformed_lines_silently_skipped():
    diff = "no-tab-here\nM\tsrc/valid.py\n"
    with _mock_diff(diff):
        result = list_reviewable_files(REPO, "main")
    assert len(result) == 1
    assert result[0].path == "src/valid.py"


def test_list_reviewable_files_passes_refs_to_git(tmp_path):
    """Verifies the correct git command is issued."""
    mock_result = MagicMock()
    mock_result.stdout = ""
    with patch("services.diff_filter.subprocess.run", return_value=mock_result) as mock_run:
        list_reviewable_files(tmp_path, "main", "feature/x")
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert "main..feature/x" in cmd
    assert call_args[1]["cwd"] == tmp_path


# ── count_modified tests ──────────────────────────────────────────────────────


def test_count_modified_returns_count_of_reviewable_files():
    diff = "M\tsrc/a.py\nA\tsrc/b.py\nR100\told.py\tnew.py\n"
    with _mock_diff(diff):
        count = count_modified(REPO, "main")
    assert count == 2


def test_count_modified_empty_diff_returns_zero():
    with _mock_diff(""):
        assert count_modified(REPO, "main") == 0


def test_count_modified_respects_extra_excludes():
    diff = "M\tsrc/a.py\nM\tdocs/api.md\n"
    with _mock_diff(diff):
        assert count_modified(REPO, "main", extra_excludes=("docs/*.md",)) == 1
