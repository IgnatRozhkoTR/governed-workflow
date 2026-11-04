"""Tests for file read and diff routes."""
import os
from datetime import datetime
from pathlib import Path

import pytest

from testing_utils import _git


def test_read_file(client, workspace):
    Path(workspace["working_dir"]).joinpath("test.txt").write_text("line1\nline2\nline3\n")
    r = client.get("/api/ws/test-project/feature/test/file?path=test.txt")
    assert r.status_code == 200
    assert r.json["lines"] == ["line1", "line2", "line3"]
    assert r.json["path"] == "test.txt"
    assert r.json["total_lines"] == 3


def test_read_file_with_range(client, workspace):
    content = "\n".join(f"line{i}" for i in range(1, 21)) + "\n"
    Path(workspace["working_dir"]).joinpath("big.txt").write_text(content)
    r = client.get("/api/ws/test-project/feature/test/file?path=big.txt&start=8&end=12")
    assert r.status_code == 200
    data = r.json
    assert data["highlight_start"] == 8
    assert data["highlight_end"] == 12
    # context window is ±5 lines: start=max(0, 8-1-5)=2, end=min(20, 12+5)=17
    assert data["start"] == 3
    assert data["end"] == 17
    assert "line8" in data["lines"]
    assert "line12" in data["lines"]


def test_read_file_missing_path(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/file")
    assert r.status_code == 400
    assert "path" in r.json["error"].lower()


def test_read_file_not_found(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/file?path=nonexistent.txt")
    assert r.status_code == 404


def test_read_file_path_traversal(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/file?path=../../etc/passwd")
    assert r.status_code == 403


def test_read_file_absolute_path(client, workspace):
    """Read a file using absolute path within the workspace working_dir."""
    abs_file = Path(workspace["working_dir"]) / "absolute_test.py"
    abs_file.write_text("external_code = True\n")
    r = client.get(f"/api/ws/test-project/feature/test/file?path={abs_file}&absolute=true")
    assert r.status_code == 200
    assert "external_code" in r.json["lines"][0]


def test_read_file_absolute_path_outside_workspace(client, workspace):
    """Absolute path outside workspace and allowed external paths is blocked."""
    # The workspace defaults to allowing /tmp/ as external path,
    # so we must test with a path outside both workspace dir AND /tmp/.
    outside_file = Path(__file__).resolve().parent / "_secret_test_file.py"
    outside_file.write_text("secret = True\n")
    try:
        r = client.get(f"/api/ws/test-project/feature/test/file?path={outside_file}&absolute=true")
        assert r.status_code == 403
    finally:
        outside_file.unlink(missing_ok=True)


def test_read_file_absolute_without_flag(client, workspace):
    """Absolute-looking path without flag is still blocked."""
    r = client.get("/api/ws/test-project/feature/test/file?path=/etc/passwd")
    assert r.status_code == 403


def test_list_files(client, workspace):
    Path(workspace["working_dir"]).joinpath("hello.py").write_text("print('hi')")
    _git(workspace["working_dir"], "add", "hello.py")
    _git(workspace["working_dir"], "commit", "-m", "Add file")
    r = client.get("/api/ws/test-project/feature/test/files")
    assert r.status_code == 200
    names = [e["name"] for e in r.json["entries"]]
    assert "hello.py" in names


def test_list_files_root_has_total(client, workspace):
    Path(workspace["working_dir"]).joinpath("a.py").write_text("x = 1")
    Path(workspace["working_dir"]).joinpath("b.py").write_text("y = 2")
    _git(workspace["working_dir"], "add", "a.py", "b.py")
    _git(workspace["working_dir"], "commit", "-m", "Add files")
    r = client.get("/api/ws/test-project/feature/test/files")
    assert r.status_code == 200
    assert "total" in r.json
    assert r.json["total"] >= 2


def test_list_files_subdirectory(client, workspace):
    subdir = Path(workspace["working_dir"]) / "subpkg"
    subdir.mkdir()
    (subdir / "service.py").write_text("class Service: pass")
    (subdir / "utils.py").write_text("def helper(): pass")
    Path(workspace["working_dir"]).joinpath("root.py").write_text("x = 1")
    _git(workspace["working_dir"], "add", "subpkg/service.py", "subpkg/utils.py", "root.py")
    _git(workspace["working_dir"], "commit", "-m", "Add subdir files")
    r = client.get("/api/ws/test-project/feature/test/files?path=subpkg")
    assert r.status_code == 200
    names = [e["name"] for e in r.json["entries"]]
    assert "service.py" in names
    assert "utils.py" in names
    assert "root.py" not in names


def test_list_files_entries_have_type(client, workspace):
    subdir = Path(workspace["working_dir"]) / "mypkg"
    subdir.mkdir()
    (subdir / "module.py").write_text("pass")
    Path(workspace["working_dir"]).joinpath("main.py").write_text("pass")
    _git(workspace["working_dir"], "add", "mypkg/module.py", "main.py")
    _git(workspace["working_dir"], "commit", "-m", "Add files and dir")
    r = client.get("/api/ws/test-project/feature/test/files")
    assert r.status_code == 200
    types = {e["name"]: e["type"] for e in r.json["entries"]}
    assert types["mypkg"] == "dir"
    assert types["main.py"] == "file"


def test_list_files_dirs_sorted_first(client, workspace):
    subdir = Path(workspace["working_dir"]) / "alpha"
    subdir.mkdir()
    (subdir / "code.py").write_text("pass")
    Path(workspace["working_dir"]).joinpath("zz_file.py").write_text("pass")
    _git(workspace["working_dir"], "add", "alpha/code.py", "zz_file.py")
    _git(workspace["working_dir"], "commit", "-m", "Add dir and file")
    r = client.get("/api/ws/test-project/feature/test/files")
    assert r.status_code == 200
    entries = r.json["entries"]
    dir_indices = [i for i, e in enumerate(entries) if e["type"] == "dir"]
    file_indices = [i for i, e in enumerate(entries) if e["type"] == "file"]
    assert all(d < f for d in dir_indices for f in file_indices)


def test_list_files_search(client, workspace):
    Path(workspace["working_dir"]).joinpath("order_service.py").write_text("pass")
    Path(workspace["working_dir"]).joinpath("order_repo.py").write_text("pass")
    Path(workspace["working_dir"]).joinpath("user_service.py").write_text("pass")
    _git(workspace["working_dir"], "add", "order_service.py", "order_repo.py", "user_service.py")
    _git(workspace["working_dir"], "commit", "-m", "Add service files")
    r = client.get("/api/ws/test-project/feature/test/files?search=order")
    assert r.status_code == 200
    names = [e["name"] for e in r.json["entries"]]
    assert "order_service.py" in names
    assert "order_repo.py" in names
    assert "user_service.py" not in names


def test_list_files_search_empty(client, workspace):
    Path(workspace["working_dir"]).joinpath("readme.txt").write_text("docs")
    _git(workspace["working_dir"], "add", "readme.txt")
    _git(workspace["working_dir"], "commit", "-m", "Add readme")
    r = client.get("/api/ws/test-project/feature/test/files?search=nonexistentxyz")
    assert r.status_code == 200
    assert r.json["entries"] == []


def test_list_files_subdirectory_no_total(client, workspace):
    subdir = Path(workspace["working_dir"]) / "pkg"
    subdir.mkdir()
    (subdir / "a.py").write_text("pass")
    _git(workspace["working_dir"], "add", "pkg/a.py")
    _git(workspace["working_dir"], "commit", "-m", "Add pkg")
    r = client.get("/api/ws/test-project/feature/test/files?path=pkg")
    assert r.status_code == 200
    assert "total" not in r.json


def test_list_files_collapses_single_child_dirs(client, workspace):
    """Single-child directory chains are collapsed into one entry."""
    wd = Path(workspace["working_dir"])
    (wd / "src" / "main" / "java").mkdir(parents=True)
    (wd / "src" / "main" / "java" / "App.java").write_text("class App {}")
    _git(workspace["working_dir"], "add", "-A")
    _git(workspace["working_dir"], "commit", "-m", "deep structure")
    r = client.get("/api/ws/test-project/feature/test/files")
    assert r.status_code == 200
    dir_entries = [e for e in r.json["entries"] if e["type"] == "dir"]
    # src/main/java should be collapsed into one entry
    assert any("src/main/java" in e["name"] for e in dir_entries)
    # path should point to the deepest collapsed dir
    collapsed = [e for e in dir_entries if "src/main/java" in e["name"]][0]
    assert collapsed["path"] == "src/main/java"


def test_list_files_workspace_not_found(client, project):
    r = client.get("/api/ws/test-project/nonexistent/branch/files")
    assert r.status_code == 404


def test_get_diff_with_changes(client, workspace):
    _git(workspace["working_dir"], "checkout", "-b", "feature/test")
    Path(workspace["working_dir"]).joinpath("new.py").write_text("x = 1\n")
    _git(workspace["working_dir"], "add", "new.py")
    _git(workspace["working_dir"], "commit", "-m", "Add new.py")
    r = client.get("/api/ws/test-project/feature/test/diff")
    assert r.status_code == 200
    paths = [f["path"] for f in r.json["files"]]
    assert "new.py" in paths


def test_get_diff_no_changes(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/diff")
    assert r.status_code == 200
    assert r.json["files"] == []


def test_get_diff_untracked_files(client, workspace):
    Path(workspace["working_dir"]).joinpath("untracked.py").write_text("y = 2\n")
    r = client.get("/api/ws/test-project/feature/test/diff")
    assert r.status_code == 200
    untracked = [f for f in r.json["files"] if f["path"] == "untracked.py"]
    assert len(untracked) == 1
    assert untracked[0]["status"] == "new"


def test_get_diff_untracked_files_in_new_directory(client, workspace):
    newpkg_dir = Path(workspace["working_dir"]) / "newpkg"
    newpkg_dir.mkdir()
    (newpkg_dir / "service.py").write_text("class Service:\n    pass\n")
    r = client.get("/api/ws/test-project/feature/test/diff")
    assert r.status_code == 200
    matched = [f for f in r.json["files"] if f["path"] == "newpkg/service.py"]
    assert len(matched) == 1
    assert matched[0]["status"] == "new"


def test_get_diff_uncommitted_mode(client, workspace):
    working_dir = workspace["working_dir"]
    # Create and commit a base file
    Path(working_dir).joinpath("base.py").write_text("x = 1\n")
    _git(working_dir, "add", "base.py")
    _git(working_dir, "commit", "-m", "Add base.py")
    # Stage a modification (creates staged change)
    Path(working_dir).joinpath("base.py").write_text("x = 1\ny = 2\n")
    _git(working_dir, "add", "base.py")
    # Make an unstaged modification on top
    Path(working_dir).joinpath("base.py").write_text("x = 1\ny = 2\nz = 3\n")
    r = client.get("/api/ws/test-project/feature/test/diff?mode=uncommitted")
    assert r.status_code == 200
    assert r.json["mode"] == "uncommitted"
    paths = [f["path"] for f in r.json["files"]]
    assert "base.py" in paths
    combined_diff = " ".join(f["diff"] for f in r.json["files"] if f["path"] == "base.py")
    assert "+y = 2" in combined_diff
    assert "+z = 3" in combined_diff


def test_get_diff_uncommitted_mode_untracked(client, workspace):
    Path(workspace["working_dir"]).joinpath("newfile.py").write_text("a = 42\n")
    r = client.get("/api/ws/test-project/feature/test/diff?mode=uncommitted")
    assert r.status_code == 200
    assert r.json["mode"] == "uncommitted"
    matched = [f for f in r.json["files"] if f["path"] == "newfile.py"]
    assert len(matched) == 1
    assert matched[0]["status"] == "new"


def test_get_diff_branch_mode_explicit(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/diff?mode=branch")
    assert r.status_code == 200
    assert r.json["mode"] == "branch"
    assert isinstance(r.json["files"], list)


def test_get_diff_returns_400_when_working_dir_missing(client, workspace, tmp_path):
    """A workspace whose worktree was removed must fail gracefully with a
    structured 400 instead of a 500 from the route handler."""
    import shutil
    from core.db import get_db

    missing_dir = tmp_path / "vanished"
    db = get_db()
    try:
        db.execute(
            "UPDATE workspaces SET working_dir = ? WHERE id = ?",
            (str(missing_dir), workspace["id"]),
        )
        db.commit()
    finally:
        db.close()

    r = client.get("/api/ws/test-project/feature/test/diff?mode=uncommitted")

    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "working_dir_unavailable"
    assert "vanished" in body["details"]


# ---------------------------------------------------------------------------
# History endpoint tests
# ---------------------------------------------------------------------------

def _make_origin_ref(working_dir, source_branch="develop"):
    """Pin origin/<source_branch> to the current HEAD so future commits are 'ahead'."""
    import subprocess
    from testing_utils import GIT_ENV
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=working_dir, capture_output=True, text=True, env=GIT_ENV
    )
    sha = result.stdout.strip()
    subprocess.run(
        ["git", "update-ref", f"refs/remotes/origin/{source_branch}", sha],
        cwd=working_dir, check=True, capture_output=True, env=GIT_ENV
    )
    return sha


def test_history_endpoint_returns_commits_for_simple_branch(client, workspace):
    wd = workspace["working_dir"]
    _make_origin_ref(wd)

    Path(wd).joinpath("a.py").write_text("x = 1\n")
    _git(wd, "add", "a.py")
    _git(wd, "commit", "-m", "First ahead commit")

    Path(wd).joinpath("b.py").write_text("y = 2\n")
    _git(wd, "add", "b.py")
    _git(wd, "commit", "-m", "Second ahead commit")

    r = client.get("/api/ws/test-project/feature/test/history")
    assert r.status_code == 200
    data = r.json
    assert data["source_branch"] == "develop"
    assert len(data["commits"]) == 2
    subjects = [c["subject"] for c in data["commits"]]
    assert "First ahead commit" in subjects
    assert "Second ahead commit" in subjects
    for commit in data["commits"]:
        assert commit["ahead_of_origin"] is True
        assert len(commit["sha"]) == 12
        assert len(commit["full_sha"]) == 40
        assert commit["author_name"] == "Test"
        assert commit["author_email"] == "test@test.com"
        assert commit["author_date"]


def test_history_endpoint_empty_when_no_new_commits(client, workspace):
    wd = workspace["working_dir"]
    _make_origin_ref(wd)

    r = client.get("/api/ws/test-project/feature/test/history")
    assert r.status_code == 200
    data = r.json
    assert data["commits"] == []
    assert data["source_branch"] == "develop"


def test_history_endpoint_handles_commit_with_special_chars(client, workspace):
    wd = workspace["working_dir"]
    _make_origin_ref(wd)

    Path(wd).joinpath("c.py").write_text("pass\n")
    _git(wd, "add", "c.py")
    import subprocess
    from testing_utils import GIT_ENV
    subprocess.run(
        ["git", "commit", "-m", 'Subject with "quotes"', "-m", "Body line one\nBody line two"],
        cwd=wd, check=True, capture_output=True, env=GIT_ENV
    )

    r = client.get("/api/ws/test-project/feature/test/history")
    assert r.status_code == 200
    commits = r.json["commits"]
    assert len(commits) == 1
    c = commits[0]
    assert '"quotes"' in c["subject"]
    assert c["body"]


# ---------------------------------------------------------------------------
# Diff mode=commit tests
# ---------------------------------------------------------------------------

def _commit_file(working_dir, filename, content, message):
    """Create, stage and commit a file; return the full SHA."""
    import subprocess
    from testing_utils import GIT_ENV
    Path(working_dir).joinpath(filename).write_text(content)
    _git(working_dir, "add", filename)
    _git(working_dir, "commit", "-m", message)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=working_dir, capture_output=True, text=True, env=GIT_ENV
    )
    return result.stdout.strip()


def test_diff_mode_commit_returns_commit_diff(client, workspace):
    wd = workspace["working_dir"]
    _commit_file(wd, "first.py", "a = 1\n", "First commit")
    sha2 = _commit_file(wd, "second.py", "b = 2\n", "Second commit")

    r = client.get(f"/api/ws/test-project/feature/test/diff?mode=commit&commit={sha2}")
    assert r.status_code == 200
    data = r.json
    assert data["mode"] == "commit"
    assert data["commit"] == sha2
    paths = [f["path"] for f in data["files"]]
    assert "second.py" in paths
    assert "first.py" not in paths


def test_diff_mode_commit_missing_sha_returns_400(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/diff?mode=commit")
    assert r.status_code == 400
    assert "commit" in r.json["error"].lower()


def test_diff_mode_commit_unknown_sha_returns_404(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/diff?mode=commit&commit=deadbeef1234")
    assert r.status_code == 404


def test_diff_mode_commit_not_in_history_returns_400(client, workspace, tmp_path):
    wd = workspace["working_dir"]

    # Create a separate repo with a commit that is not an ancestor of wd HEAD.
    other_repo = tmp_path / "other"
    other_repo.mkdir()
    import subprocess
    from testing_utils import GIT_ENV
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True, env=GIT_ENV)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "Orphan commit"],
        cwd=str(other_repo), check=True, capture_output=True, env=GIT_ENV
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(other_repo), capture_output=True, text=True, env=GIT_ENV
    )
    orphan_sha = result.stdout.strip()

    # Fetch the orphan commit object into wd using git fetch.
    subprocess.run(
        ["git", "fetch", str(other_repo), "HEAD"],
        cwd=wd, check=True, capture_output=True, env=GIT_ENV
    )

    r = client.get(f"/api/ws/test-project/feature/test/diff?mode=commit&commit={orphan_sha}")
    assert r.status_code == 400
    assert "ancestor" in r.json["error"].lower()


def test_diff_mode_branch_still_works(client, workspace):
    wd = workspace["working_dir"]
    # Pin origin/develop before adding the commit so the new file appears in diff.
    _make_origin_ref(wd)
    _commit_file(wd, "branch_file.py", "z = 99\n", "Branch commit")

    r = client.get("/api/ws/test-project/feature/test/diff?mode=branch")
    assert r.status_code == 200
    data = r.json
    assert data["mode"] == "branch"
    paths = [f["path"] for f in data["files"]]
    assert "branch_file.py" in paths


def test_diff_mode_uncommitted_still_works(client, workspace):
    wd = workspace["working_dir"]
    Path(wd).joinpath("staged.py").write_text("s = 1\n")
    _git(wd, "add", "staged.py")

    r = client.get("/api/ws/test-project/feature/test/diff?mode=uncommitted")
    assert r.status_code == 200
    data = r.json
    assert data["mode"] == "uncommitted"
    paths = [f["path"] for f in data["files"]]
    assert "staged.py" in paths


def test_diff_mode_commit_does_not_include_untracked(client, workspace):
    wd = workspace["working_dir"]
    sha = _commit_file(wd, "tracked.py", "t = 1\n", "Tracked commit")

    # Add an untracked file that should NOT appear in commit mode.
    Path(wd).joinpath("untracked_extra.py").write_text("u = 99\n")

    r = client.get(f"/api/ws/test-project/feature/test/diff?mode=commit&commit={sha}")
    assert r.status_code == 200
    paths = [f["path"] for f in r.json["files"]]
    assert "tracked.py" in paths
    assert "untracked_extra.py" not in paths


# ---------------------------------------------------------------------------
# list_files — untracked / .gitignore coverage
# ---------------------------------------------------------------------------

def test_list_files_includes_untracked_file(client, workspace):
    wd = Path(workspace["working_dir"])

    (wd / "tracked.py").write_text("x = 1")
    _git(str(wd), "add", "tracked.py")
    _git(str(wd), "commit", "-m", "Add tracked")

    (wd / "untracked_new.py").write_text("y = 2")

    r = client.get("/api/ws/test-project/feature/test/files")

    assert r.status_code == 200
    names = [e["name"] for e in r.json["entries"]]
    assert "untracked_new.py" in names
    assert "tracked.py" in names


def test_list_files_search_finds_untracked_file(client, workspace):
    wd = Path(workspace["working_dir"])
    (wd / "untracked_widget.py").write_text("pass")

    r = client.get("/api/ws/test-project/feature/test/files?search=widget")

    assert r.status_code == 200
    names = [e["name"] for e in r.json["entries"]]
    assert "untracked_widget.py" in names


def test_list_files_excludes_gitignored_file(client, workspace):
    wd = Path(workspace["working_dir"])

    (wd / ".gitignore").write_text("*.secret\n")
    _git(str(wd), "add", ".gitignore")
    _git(str(wd), "commit", "-m", "Add .gitignore")

    (wd / "hidden.secret").write_text("do not show")

    r = client.get("/api/ws/test-project/feature/test/files")

    assert r.status_code == 200
    names = [e["name"] for e in r.json["entries"]]
    assert "hidden.secret" not in names


# ---------------------------------------------------------------------------
# write_file (PUT /file) tests
# ---------------------------------------------------------------------------

def test_write_file_creates_and_reads_back(client, workspace):
    wd = workspace["working_dir"]

    put_r = client.put(
        "/api/ws/test-project/feature/test/file",
        json={"path": "new_doc.md", "content": "# Hello\nworld\n"},
        content_type="application/json",
    )

    assert put_r.status_code == 200
    assert put_r.json["ok"] is True

    get_r = client.get("/api/ws/test-project/feature/test/file?path=new_doc.md")
    assert get_r.status_code == 200
    assert get_r.json["lines"] == ["# Hello", "world"]


def test_write_file_creates_parent_dirs(client, workspace):
    put_r = client.put(
        "/api/ws/test-project/feature/test/file",
        json={"path": "deep/nested/dir/file.txt", "content": "hi"},
        content_type="application/json",
    )

    assert put_r.status_code == 200
    assert (Path(workspace["working_dir"]) / "deep" / "nested" / "dir" / "file.txt").exists()


def test_write_file_empty_content_when_absent(client, workspace):
    put_r = client.put(
        "/api/ws/test-project/feature/test/file",
        json={"path": "empty.txt"},
        content_type="application/json",
    )

    assert put_r.status_code == 200
    assert (Path(workspace["working_dir"]) / "empty.txt").read_text() == ""


def test_write_file_missing_path_returns_400(client, workspace):
    r = client.put(
        "/api/ws/test-project/feature/test/file",
        json={"content": "some content"},
        content_type="application/json",
    )

    assert r.status_code == 400
    assert "path" in r.json["error"].lower()


def test_write_file_path_traversal_returns_403(client, workspace):
    r = client.put(
        "/api/ws/test-project/feature/test/file",
        json={"path": "../escape/file.txt", "content": "bad"},
        content_type="application/json",
    )

    assert r.status_code == 403


# ---------------------------------------------------------------------------
# get_repos endpoint tests
# ---------------------------------------------------------------------------

def test_get_repos_root_entry_is_first(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/repos")
    assert r.status_code == 200
    repos = r.json["repos"]
    assert repos[0]["path"] == "."


def test_get_repos_lists_subdir_with_git_directory(client, workspace):
    sub = Path(workspace["working_dir"]) / "sub_repo"
    sub.mkdir()
    _git(sub, "init")

    r = client.get("/api/ws/test-project/feature/test/repos")

    assert r.status_code == 200
    paths = [repo["path"] for repo in r.json["repos"]]
    assert "sub_repo" in paths


def test_get_repos_lists_subdir_with_git_file_worktree(client, workspace):
    sub = Path(workspace["working_dir"]) / "worktree_repo"
    sub.mkdir()
    (sub / ".git").write_text("gitdir: ../.git/worktrees/worktree_repo\n")

    r = client.get("/api/ws/test-project/feature/test/repos")

    assert r.status_code == 200
    paths = [repo["path"] for repo in r.json["repos"]]
    assert "worktree_repo" in paths


def test_get_repos_excludes_subdir_without_git(client, workspace):
    (Path(workspace["working_dir"]) / "plain_dir").mkdir()

    r = client.get("/api/ws/test-project/feature/test/repos")

    assert r.status_code == 200
    paths = [repo["path"] for repo in r.json["repos"]]
    assert "plain_dir" not in paths


def test_get_repos_excludes_hidden_dir_with_git(client, workspace):
    hidden = Path(workspace["working_dir"]) / ".hidden_repo"
    hidden.mkdir()
    _git(hidden, "init")

    r = client.get("/api/ws/test-project/feature/test/repos")

    assert r.status_code == 200
    paths = [repo["path"] for repo in r.json["repos"]]
    assert ".hidden_repo" not in paths


def test_get_repos_excludes_node_modules_with_git(client, workspace):
    node_modules = Path(workspace["working_dir"]) / "node_modules"
    node_modules.mkdir()
    _git(node_modules, "init")

    r = client.get("/api/ws/test-project/feature/test/repos")

    assert r.status_code == 200
    paths = [repo["path"] for repo in r.json["repos"]]
    assert "node_modules" not in paths


def test_get_repos_subdirs_sorted_alphabetically(client, workspace):
    wd = Path(workspace["working_dir"])
    for name in ("zeta_repo", "alpha_repo", "mid_repo"):
        sub = wd / name
        sub.mkdir()
        _git(sub, "init")

    r = client.get("/api/ws/test-project/feature/test/repos")

    assert r.status_code == 200
    paths = [repo["path"] for repo in r.json["repos"]]
    assert paths == [".", "alpha_repo", "mid_repo", "zeta_repo"]


def test_get_repos_excludes_depth_two_repo(client, workspace):
    nested = Path(workspace["working_dir"]) / "outer_dir" / "inner_repo"
    nested.mkdir(parents=True)
    _git(nested, "init")

    r = client.get("/api/ws/test-project/feature/test/repos")

    assert r.status_code == 200
    paths = [repo["path"] for repo in r.json["repos"]]
    assert "outer_dir" not in paths
    assert not any("inner_repo" in p for p in paths)


# ---------------------------------------------------------------------------
# repo= param validation shared across diff / branches / history
# ---------------------------------------------------------------------------

REPO_SCOPED_ENDPOINTS = ("diff", "branches", "history")


def test_repo_param_dot_and_omitted_are_equivalent(client, workspace):
    r_omitted = client.get("/api/ws/test-project/feature/test/branches")
    r_dot = client.get("/api/ws/test-project/feature/test/branches?repo=.")

    assert r_omitted.status_code == 200
    assert r_dot.status_code == 200
    assert r_omitted.json == r_dot.json


def test_repo_param_parent_traversal_returns_invalid_repo(client, workspace):
    for endpoint in REPO_SCOPED_ENDPOINTS:
        r = client.get(f"/api/ws/test-project/feature/test/{endpoint}?repo=../something")
        assert r.status_code == 400, endpoint
        assert r.json["error"] == "invalid_repo", endpoint


def test_repo_param_absolute_path_returns_invalid_repo(client, workspace):
    for endpoint in REPO_SCOPED_ENDPOINTS:
        r = client.get(f"/api/ws/test-project/feature/test/{endpoint}?repo=/etc")
        assert r.status_code == 400, endpoint
        assert r.json["error"] == "invalid_repo", endpoint


def test_repo_param_existing_dir_without_git_returns_repo_not_found(client, workspace):
    (Path(workspace["working_dir"]) / "no_git_here").mkdir()

    for endpoint in REPO_SCOPED_ENDPOINTS:
        r = client.get(f"/api/ws/test-project/feature/test/{endpoint}?repo=no_git_here")
        assert r.status_code == 400, endpoint
        assert r.json["error"] == "repo_not_found", endpoint


def test_repo_param_nonexistent_dir_returns_repo_not_found(client, workspace):
    for endpoint in REPO_SCOPED_ENDPOINTS:
        r = client.get(f"/api/ws/test-project/feature/test/{endpoint}?repo=does_not_exist")
        assert r.status_code == 400, endpoint
        assert r.json["error"] == "repo_not_found", endpoint


# ---------------------------------------------------------------------------
# repo= param actually scopes git operations to the inner repository
# ---------------------------------------------------------------------------

def _init_inner_repo(root_wd, name, branch="inner-main"):
    """Create a nested git repository (separate from the root repo) with an initial commit."""
    inner = Path(root_wd) / name
    inner.mkdir()
    _git(inner, "init")
    _git(inner, "checkout", "-b", branch)
    _git(inner, "config", "user.name", "Inner")
    _git(inner, "config", "user.email", "inner@test.com")
    (inner / "inner_seed.py").write_text("seed = 1\n")
    _git(inner, "add", "inner_seed.py")
    _git(inner, "commit", "-m", "Inner initial commit")
    return inner


def test_repo_param_scopes_uncommitted_diff_to_inner_repo(client, workspace):
    wd = Path(workspace["working_dir"])
    (wd / "root_uncommitted.py").write_text("root = 1\n")

    inner = _init_inner_repo(wd, "inner_repo")
    (inner / "inner_uncommitted.py").write_text("inner = 1\n")

    r = client.get("/api/ws/test-project/feature/test/diff?mode=uncommitted&repo=inner_repo")

    assert r.status_code == 200
    paths = [f["path"] for f in r.json["files"]]
    assert "inner_uncommitted.py" in paths
    assert "root_uncommitted.py" not in paths
    assert "inner_repo/inner_uncommitted.py" not in paths


def test_repo_param_scopes_branches_to_inner_repo(client, workspace):
    wd = Path(workspace["working_dir"])
    inner = _init_inner_repo(wd, "inner_repo2", branch="inner-main")
    _git(inner, "branch", "inner-feature")

    r = client.get("/api/ws/test-project/feature/test/branches?repo=inner_repo2")

    assert r.status_code == 200
    names = [b["name"] for b in r.json["branches"]]
    assert "inner-main" in names
    assert "inner-feature" in names
    assert "develop" not in names


# ---------------------------------------------------------------------------
# base= override for mode=branch diffs
# ---------------------------------------------------------------------------

def test_diff_branch_mode_response_includes_source_branch_as_base_when_no_override(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/diff?mode=branch")

    assert r.status_code == 200
    assert r.json["base"] == "develop"


def test_diff_base_override_computes_against_chosen_branch(client, workspace):
    wd = workspace["working_dir"]
    _commit_file(wd, "on_develop.py", "d = 1\n", "Develop-only file")

    _git(wd, "checkout", "-b", "other-base")
    _commit_file(wd, "on_other_base.py", "o = 1\n", "Other-base-only file")

    _git(wd, "checkout", "-b", "feature/test", "develop")
    _commit_file(wd, "on_feature.py", "f = 1\n", "Feature-only file")

    r_default = client.get("/api/ws/test-project/feature/test/diff?mode=branch")
    assert r_default.status_code == 200
    default_paths = {f["path"] for f in r_default.json["files"]}
    assert "on_feature.py" in default_paths
    assert "on_other_base.py" not in default_paths
    assert r_default.json["base"] == "develop"

    r_base = client.get("/api/ws/test-project/feature/test/diff?mode=branch&base=other-base")
    assert r_base.status_code == 200
    base_paths = {f["path"] for f in r_base.json["files"]}
    assert "on_feature.py" in base_paths
    assert "on_other_base.py" in base_paths
    assert r_base.json["base"] == "other-base"


def test_diff_base_override_with_no_differences_returns_empty_files(client, workspace):
    wd = workspace["working_dir"]
    _git(wd, "checkout", "-b", "same-as-feature")
    _git(wd, "checkout", "-b", "feature/test")

    r = client.get("/api/ws/test-project/feature/test/diff?mode=branch&base=same-as-feature")

    assert r.status_code == 200
    assert r.json["files"] == []
    assert r.json["base"] == "same-as-feature"


def test_diff_base_override_unknown_ref_returns_400(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/diff?mode=branch&base=does-not-exist")

    assert r.status_code == 400
    assert r.json == {"error": "base_ref_not_found", "base": "does-not-exist"}


def test_diff_base_ignored_for_uncommitted_mode(client, workspace):
    wd = workspace["working_dir"]
    Path(wd).joinpath("scratch.py").write_text("s = 1\n")

    r = client.get("/api/ws/test-project/feature/test/diff?mode=uncommitted&base=does-not-exist")

    assert r.status_code == 200
    assert r.json["mode"] == "uncommitted"
    paths = [f["path"] for f in r.json["files"]]
    assert "scratch.py" in paths


def test_diff_base_ignored_for_commit_mode(client, workspace):
    wd = workspace["working_dir"]
    sha = _commit_file(wd, "committed.py", "c = 1\n", "Commit for base-ignore test")

    r = client.get(f"/api/ws/test-project/feature/test/diff?mode=commit&commit={sha}&base=does-not-exist")

    assert r.status_code == 200
    assert r.json["mode"] == "commit"
    paths = [f["path"] for f in r.json["files"]]
    assert "committed.py" in paths


# ---------------------------------------------------------------------------
# repo= resolution when working_dir is a worktree subdirectory of the project
# (mirrors <project>/.claude/worktrees/<branch> in production)
# ---------------------------------------------------------------------------

@pytest.fixture
def nested_workspace(clean_db):
    """Project whose path is a parent repo, with the workspace working_dir a
    genuine git-worktree subdirectory of the project path, matching the real
    <project>/.claude/worktrees/<branch> layout."""
    import tempfile
    from core.db import get_db

    tmp_root = Path(tempfile.mkdtemp())
    project_root = tmp_root / "project"
    project_root.mkdir()
    _git(project_root, "init")
    _git(project_root, "config", "user.name", "Test")
    _git(project_root, "config", "user.email", "test@test.com")
    _git(project_root, "checkout", "-b", "develop")
    (project_root / ".gitignore").write_text("")
    _git(project_root, "add", ".")
    _git(project_root, "commit", "-m", "Initial commit")

    worktree_dir = project_root / ".claude" / "worktrees" / "feature-test"
    worktree_dir.parent.mkdir(parents=True)
    _git(project_root, "worktree", "add", "-b", "feature/test", str(worktree_dir), "develop")

    db = get_db()
    registered = datetime.now().isoformat()
    db.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        ("test-project", "Test Project", str(project_root), registered),
    )
    now = datetime.now().isoformat()
    cursor = db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?)",
        ("test-project", "feature/test", "feature-test", str(worktree_dir),
         now, '{"description":"","systemDiagram":"","execution":[]}', "develop"),
    )
    ws_id = cursor.lastrowid
    db.commit()
    db.close()

    return {
        "project_path": str(project_root),
        "working_dir": str(worktree_dir),
        "ws_id": ws_id,
    }


def test_get_repos_lists_inner_repo_under_project_not_under_worktree(client, nested_workspace):
    inner = Path(nested_workspace["project_path"]) / "inner_repo"
    inner.mkdir()
    _git(inner, "init")

    r = client.get("/api/ws/test-project/feature/test/repos")

    assert r.status_code == 200
    paths = [repo["path"] for repo in r.json["repos"]]
    assert paths[0] == "."
    assert "inner_repo" in paths
    assert not (Path(nested_workspace["working_dir"]) / "inner_repo").exists()


def test_repo_param_resolves_inner_repo_under_project_for_diff_and_branches(client, nested_workspace):
    inner = _init_inner_repo(nested_workspace["project_path"], "inner_repo")
    (inner / "inner_uncommitted.py").write_text("inner = 1\n")
    _git(inner, "branch", "inner-feature")

    r_diff = client.get("/api/ws/test-project/feature/test/diff?mode=uncommitted&repo=inner_repo")
    assert r_diff.status_code == 200
    diff_paths = [f["path"] for f in r_diff.json["files"]]
    assert "inner_uncommitted.py" in diff_paths

    r_branches = client.get("/api/ws/test-project/feature/test/branches?repo=inner_repo")
    assert r_branches.status_code == 200
    branch_names = [b["name"] for b in r_branches.json["branches"]]
    assert "inner-main" in branch_names
    assert "inner-feature" in branch_names


def test_repo_param_traversal_outside_project_path_still_rejected(client, nested_workspace):
    for endpoint in REPO_SCOPED_ENDPOINTS:
        r = client.get(f"/api/ws/test-project/feature/test/{endpoint}?repo=../something")
        assert r.status_code == 400, endpoint
        assert r.json["error"] == "invalid_repo", endpoint


# ---------------------------------------------------------------------------
# multi-repo project: get_repos / diff / history / branches scoping
# ---------------------------------------------------------------------------

def _create_multi_workspace(client, project, branch, **extra):
    payload = {"branch": branch, "worktree": True}
    payload.update(extra)
    return client.post(f"/api/projects/{project['id']}/workspaces", json=payload)


def test_get_repos_multi_project_returns_only_attached_repos_no_root_entry(client, multi_project):
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    branch = "feature/repos-multi"
    r = _create_multi_workspace(client, multi_project, branch, repos=[repo_a_id])
    assert r.status_code == 201, r.json

    r_repos = client.get(f"/api/ws/{multi_project['id']}/{branch}/repos")
    assert r_repos.status_code == 200
    repos = r_repos.json["repos"]
    assert repos == [{"path": "service-a", "name": "service-a"}]


def test_get_repos_multi_project_no_attached_repos_returns_empty_list(client, multi_project):
    branch = "feature/repos-none"
    r = _create_multi_workspace(client, multi_project, branch)
    assert r.status_code == 201, r.json

    r_repos = client.get(f"/api/ws/{multi_project['id']}/{branch}/repos")
    assert r_repos.status_code == 200
    assert r_repos.json["repos"] == []


def test_get_repos_single_project_unchanged(client, workspace):
    r = client.get("/api/ws/test-project/feature/test/repos")
    assert r.status_code == 200
    assert r.json["repos"][0]["path"] == "."


def test_diff_history_branches_multi_project_resolve_attached_repo_worktree(client, multi_project):
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    repo_b_id = multi_project["repos"]["service-b"]["id"]
    branch = "feature/scoped-multi"
    r = _create_multi_workspace(client, multi_project, branch, repos=[repo_a_id, repo_b_id])
    assert r.status_code == 201, r.json

    worktree_b = Path(r.json["attached_repos"][1]["worktree_path"])
    assert worktree_b.name == "service-b"
    (worktree_b / "uncommitted.py").write_text("x = 1\n")

    r_diff = client.get(f"/api/ws/{multi_project['id']}/{branch}/diff?mode=uncommitted&repo=service-b")
    assert r_diff.status_code == 200, r_diff.json
    diff_paths = [f["path"] for f in r_diff.json["files"]]
    assert "uncommitted.py" in diff_paths

    r_history = client.get(f"/api/ws/{multi_project['id']}/{branch}/history?repo=service-b")
    assert r_history.status_code == 200, r_history.json

    r_branches = client.get(f"/api/ws/{multi_project['id']}/{branch}/branches?repo=service-b")
    assert r_branches.status_code == 200, r_branches.json


def test_diff_history_branches_multi_project_missing_repo_param_returns_repo_required(client, multi_project):
    branch = "feature/scoped-multi-required"
    r = _create_multi_workspace(client, multi_project, branch)
    assert r.status_code == 201, r.json

    for endpoint in REPO_SCOPED_ENDPOINTS:
        resp = client.get(f"/api/ws/{multi_project['id']}/{branch}/{endpoint}")
        assert resp.status_code == 400, endpoint
        assert resp.json["error"] == "repo_required", endpoint


def test_diff_history_branches_multi_project_unattached_repo_returns_repo_not_found(client, multi_project):
    branch = "feature/scoped-multi-unattached"
    repo_a_id = multi_project["repos"]["service-a"]["id"]
    r = _create_multi_workspace(client, multi_project, branch, repos=[repo_a_id])
    assert r.status_code == 201, r.json

    for endpoint in REPO_SCOPED_ENDPOINTS:
        resp = client.get(f"/api/ws/{multi_project['id']}/{branch}/{endpoint}?repo=service-c")
        assert resp.status_code == 400, endpoint
        assert resp.json["error"] == "repo_not_found", endpoint
