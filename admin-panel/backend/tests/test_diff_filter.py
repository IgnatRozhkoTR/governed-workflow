"""Tests for diff_filter: reviewable file list extraction and exclusion rules."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import subprocess

from services.diff_filter import (
    list_reviewable_files,
    count_modified,
    _parse_line,
    resolve_review_base,
    get_branch_diff,
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


def test_list_reviewable_files_excludes_deleted():
    with _mock_diff("D\tsrc/legacy.py\n"):
        result = list_reviewable_files(REPO, "main")
    assert result == []


def test_list_reviewable_files_deleted_mixed_with_others():
    diff = "D\tsrc/old.py\nM\tsrc/new.py\n"
    with _mock_diff(diff):
        result = list_reviewable_files(REPO, "main")
    assert len(result) == 1
    assert result[0].path == "src/new.py"


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


def test_list_reviewable_files_excludes_nested_package_lock():
    diff = "M\tfrontend/package-lock.json\nM\tapps/client/yarn.lock\n"
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
    """Verifies the correct git command is issued with merge-base (three-dot) semantics."""
    mock_result = MagicMock()
    mock_result.stdout = ""
    with patch("services.diff_filter.subprocess.run", return_value=mock_result) as mock_run:
        list_reviewable_files(tmp_path, "main", "feature/x")
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert "main...feature/x" in cmd
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


# ── resolve_review_base + three-dot integration tests (real git) ──────────────

def _g(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _make_repo_with_origin(tmp_path):
    """develop@X with a.py, pushed to a bare origin. Returns (repo, X_sha)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _g(repo, "init")
    _g(repo, "config", "user.name", "Test")
    _g(repo, "config", "user.email", "test@test.com")
    _g(repo, "checkout", "-b", "develop")
    (repo / "a.py").write_text("a = 1\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "X: initial")
    x_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                           check=True, capture_output=True, text=True).stdout.strip()
    _g(repo, "remote", "add", "origin", str(origin))
    _g(repo, "push", "-u", "origin", "develop")
    return repo, x_sha


def test_resolve_review_base_prefers_origin_when_remote_exists(tmp_path):
    repo, _ = _make_repo_with_origin(tmp_path)

    resolved = resolve_review_base(repo, "develop")

    assert resolved == "origin/develop"


def test_resolve_review_base_falls_back_to_local_without_remote(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _g(repo, "init")
    _g(repo, "config", "user.name", "Test")
    _g(repo, "config", "user.email", "test@test.com")
    _g(repo, "checkout", "-b", "develop")
    (repo / "a.py").write_text("a = 1\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "init")

    assert resolve_review_base(repo, "develop") == "develop"


def test_resolve_review_base_passes_through_qualified_ref(tmp_path):
    repo, _ = _make_repo_with_origin(tmp_path)

    assert resolve_review_base(repo, "origin/develop") == "origin/develop"


def test_count_modified_ignores_tickets_merged_into_base_after_branch_point(tmp_path):
    """Reproduces MP-200: stale local base inflates the count; the fresh
    origin base + three-dot merge-base counts only the branch's own files."""
    repo, x_sha = _make_repo_with_origin(tmp_path)

    # origin/develop advances with 5 unrelated tickets (then push).
    for i in range(1, 6):
        (repo / f"t{i}.py").write_text(f"t = {i}\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "Y: five merged tickets")
    _g(repo, "push", "origin", "develop")

    # Local develop is reset BEHIND (stale), simulating a never-pulled worktree base.
    # Detach HEAD first so git allows force-moving the currently checked-out branch.
    _g(repo, "checkout", "--detach", "HEAD")
    _g(repo, "branch", "-f", "develop", x_sha)

    # Feature branch is cut from the *fresh* origin/develop, then adds one file.
    _g(repo, "checkout", "-b", "feature", "origin/develop")
    (repo / "b.py").write_text("b = 1\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "feature: one file")

    # Against the stale LOCAL base the count is inflated (the bug).
    assert count_modified(repo, "develop") == 6

    # resolve_review_base + count = only the branch's own file.
    resolved = resolve_review_base(repo, "develop")
    assert resolved == "origin/develop"
    assert count_modified(repo, resolved) == 1


def test_resolve_review_base_falls_back_when_repo_path_invalid(tmp_path):
    missing = tmp_path / "does-not-exist"

    assert resolve_review_base(missing, "develop") == "develop"


# ── get_branch_diff tests (real git) ─────────────────────────────────────────


def _make_two_branch_repo(tmp_path):
    """base branch with existing.py, feature branch adds new_feature.py and modifies existing.py."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _g(repo, "init")
    _g(repo, "config", "user.name", "Test")
    _g(repo, "config", "user.email", "test@test.com")
    _g(repo, "checkout", "-b", "base")
    (repo / "existing.py").write_text("x = 1\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "base commit")

    _g(repo, "checkout", "-b", "feature")
    (repo / "new_feature.py").write_text("MARKER_ADDED_LINE = 1\ndef hello():\n    return 'world'\n")
    (repo / "existing.py").write_text("x = 1\ny = 2\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "add new feature and modify existing")
    return repo


def test_get_branch_diff_returns_stat_and_patch_for_real_repo(tmp_path):
    repo = _make_two_branch_repo(tmp_path)

    result = get_branch_diff(repo, "base")

    assert result.startswith("Summary:\n")
    assert "Diff:\n" in result
    assert "new_feature.py" in result
    assert "MARKER_ADDED_LINE" in result
    assert "+" in result


def test_get_branch_diff_returns_empty_string_when_base_ref_missing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _g(repo, "init")
    _g(repo, "config", "user.name", "Test")
    _g(repo, "config", "user.email", "test@test.com")
    _g(repo, "checkout", "-b", "main")
    (repo / "a.py").write_text("a = 1\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "init")

    result = get_branch_diff(repo, "nonexistent-ref")

    assert result == ""
