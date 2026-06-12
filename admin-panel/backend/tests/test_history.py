"""Integration tests for commit history mutation endpoints (rename, undo, squash)."""
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from testing_utils import GIT_ENV, _git


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _rev_parse(repo, ref="HEAD"):
    result = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
    )
    return result.stdout.strip()


def _log_subject(repo, ref="HEAD"):
    result = subprocess.run(
        ["git", "log", "-1", "--format=%s", ref],
        cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
    )
    return result.stdout.strip()


def _tree_sha(repo, ref="HEAD"):
    return _rev_parse(repo, f"{ref}^{{tree}}")


def _author(repo, ref="HEAD"):
    """Return (author_name, author_email) of <ref>."""
    result = subprocess.run(
        ["git", "show", "-s", "--format=%an%n%ae", ref],
        cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
    )
    name, email = result.stdout.splitlines()[:2]
    return name, email


def _subjects_oldest_first(repo, source_branch="develop"):
    """Return local-unpushed commit subjects in oldest-first order."""
    result = subprocess.run(
        ["git", "log", "--reverse", f"origin/{source_branch}..HEAD", "--format=%s"],
        cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
    )
    return [line for line in result.stdout.splitlines() if line]


def _porcelain(repo):
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
    )
    return result.stdout.strip()


def _commit_file(repo, filename, content, message):
    path = Path(repo) / filename
    path.write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _rev_parse(repo)


def _set_origin_ref(repo, source_branch="develop"):
    """Pin refs/remotes/origin/<source_branch> to current HEAD."""
    sha = _rev_parse(repo)
    subprocess.run(
        ["git", "update-ref", f"refs/remotes/origin/{source_branch}", sha],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )
    return sha


@pytest.fixture
def history_repo(tmp_path):
    """Real git repo with a bare origin, 3 pushed commits, and 3 local commits.

    Layout:
        bare_origin/ — bare repo acting as origin
        repo/        — working repo with remote 'origin' pointing at bare_origin

    Pushed commits: pushed-1, pushed-2, pushed-3  (on develop)
    Local commits:  local-1, local-2, local-3      (ahead of origin/develop)
    """
    bare = tmp_path / "bare_origin"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare"], cwd=str(bare), check=True, capture_output=True, env=GIT_ENV)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "checkout", "-b", "develop")
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )

    # 3 pushed commits
    for i in range(1, 4):
        _commit_file(repo, f"pushed_{i}.py", f"x = {i}\n", f"pushed-{i}")

    subprocess.run(
        ["git", "push", "-u", "origin", "develop"],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )

    # 3 local-only commits
    for i in range(1, 4):
        _commit_file(repo, f"local_{i}.py", f"y = {i}\n", f"local-{i}")

    return repo


@pytest.fixture
def history_workspace(history_repo, clean_db):
    """Register history_repo as a project + workspace in the test DB."""
    from core.db import get_db
    db = get_db()
    now = datetime.now().isoformat()
    project_id = "hist-project"
    db.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "Hist Project", str(history_repo), now)
    )
    cursor = db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?)",
        (
            project_id, "develop", "develop", str(history_repo),
            now,
            '{"description":"","systemDiagram":"","execution":[]}', "develop"
        )
    )
    ws_id = cursor.lastrowid
    db.commit()
    db.close()
    return {
        "id": ws_id,
        "project_id": project_id,
        "branch": "develop",
        "working_dir": str(history_repo),
    }


# ---------------------------------------------------------------------------
# Rename tests
# ---------------------------------------------------------------------------

def test_rename_happy_path(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"message": "renamed-local-3"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["subject"] == "renamed-local-3"
    assert _log_subject(repo) == "renamed-local-3"


def test_rename_rejects_pushed_head(client, history_workspace, tmp_path):
    """If we check out a pushed commit (detach HEAD to a pushed SHA) the branch
    check fires first. Instead, simulate by temporarily moving origin ref forward
    to equal HEAD so HEAD is 'pushed'."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    # Move origin/develop to current HEAD so the head commit is no longer ahead
    _set_origin_ref(repo, "develop")

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"message": "should fail"},
    )
    assert r.status_code == 400
    assert "pushed" in r.get_json()["error"].lower()


def test_rename_rejects_dirty_tree(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    # Create an untracked file that is tracked-by-scope would appear in `git status`
    # Actually use a modified tracked file so git status --porcelain shows output
    pushed_file = Path(repo) / "pushed_1.py"
    pushed_file.write_text("modified content\n")

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"message": "should fail"},
    )
    assert r.status_code == 400
    assert "clean" in r.get_json()["error"].lower()

    # restore
    pushed_file.write_text("x = 1\n")


def test_rename_rejects_detached_head(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    sha = _rev_parse(repo)
    subprocess.run(
        ["git", "checkout", "--detach", sha],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )

    try:
        r = client.post(
            f"/api/ws/{pid}/develop/history/rename",
            json={"message": "should fail"},
        )
        assert r.status_code == 400
        error = r.get_json()["error"].lower()
        assert "detached" in error or "expected" in error
    finally:
        _git(repo, "checkout", "develop")


def test_rename_rejects_empty_message(client, history_workspace):
    pid = history_workspace["project_id"]
    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"message": ""},
    )
    assert r.status_code == 400
    assert "message" in r.get_json()["error"].lower()


def test_rename_head_via_explicit_sha_uses_amend_path(client, history_workspace):
    """Passing the HEAD sha explicitly behaves like the omitted-sha amend path:
    message changes, commit count unchanged, HEAD identity preserved by content."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    head = _rev_parse(repo)
    count_before = len(_local_shas(repo))
    head_tree = _tree_sha(repo, head)

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"sha": head, "message": "renamed-head-explicit"},
    )

    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert _log_subject(repo) == "renamed-head-explicit"
    assert len(_local_shas(repo)) == count_before
    assert _tree_sha(repo) == head_tree


def test_rename_middle_commit_rewrites_only_target_message(client, history_workspace):
    """Reword the MIDDLE local commit (local-2). Surrounding commits keep their
    exact messages, every commit keeps its original tree, count is unchanged,
    and HEAD moves to a new SHA."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    shas = _local_shas(repo)  # newest-first: [local-3, local-2, local-1]
    assert [_log_subject(repo, s) for s in shas] == ["local-3", "local-2", "local-1"]
    middle = shas[1]

    head_before = _rev_parse(repo)
    trees_before = {
        "local-1": _tree_sha(repo, shas[2]),
        "local-2": _tree_sha(repo, shas[1]),
        "local-3": _tree_sha(repo, shas[0]),
    }
    count_before = len(shas)

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"sha": middle, "message": "renamed-local-2"},
    )

    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["subject"] == "renamed-local-2"
    assert data["reworded_sha"] != middle

    new_shas = _local_shas(repo)
    assert len(new_shas) == count_before
    assert _rev_parse(repo) != head_before

    new_subjects = [_log_subject(repo, s) for s in new_shas]
    assert new_subjects == ["local-3", "renamed-local-2", "local-1"]

    assert _tree_sha(repo, new_shas[2]) == trees_before["local-1"]
    assert _tree_sha(repo, new_shas[1]) == trees_before["local-2"]
    assert _tree_sha(repo, new_shas[0]) == trees_before["local-3"]


def test_rename_oldest_local_commit_preserves_descendants(client, history_workspace):
    """Reword the OLDEST local commit (local-1, whose parent is the pushed base).
    Both descendants keep their messages and all trees are preserved."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    shas = _local_shas(repo)  # [local-3, local-2, local-1]
    oldest = shas[-1]
    pushed_base = _rev_parse(repo, "origin/develop")

    trees_before = [_tree_sha(repo, s) for s in shas]

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"sha": oldest, "message": "renamed-local-1"},
    )

    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    new_shas = _local_shas(repo)
    assert len(new_shas) == 3
    assert [_log_subject(repo, s) for s in new_shas] == ["local-3", "local-2", "renamed-local-1"]

    # Reworded oldest still sits directly on the unchanged pushed base
    assert _rev_parse(repo, f"{new_shas[-1]}~1") == pushed_base
    assert [_tree_sha(repo, s) for s in new_shas] == trees_before


def test_rename_root_commit_without_parent(client, tmp_path, clean_db):
    """Reword the ROOT commit (no parent) of a repo whose local stack starts at
    the initial commit. The commit-tree path must handle the missing parent."""
    bare = tmp_path / "bare_root"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare"], cwd=str(bare), check=True, capture_output=True, env=GIT_ENV)

    repo = tmp_path / "rootrepo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "checkout", "-b", "main")
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )

    # Unrelated seed so origin/main exists but does not contain our local stack
    seed = tmp_path / "seed_root"
    seed.mkdir()
    _git(seed, "init")
    _git(seed, "checkout", "-b", "main")
    _commit_file(seed, "seed.py", "s = 0\n", "seed-commit")
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=str(seed), check=True, capture_output=True, env=GIT_ENV
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=str(seed), check=True, capture_output=True, env=GIT_ENV
    )
    subprocess.run(
        ["git", "fetch", "origin"],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )

    # Local stack on an unrelated root commit, plus one descendant
    root = _commit_file(repo, "root.py", "r = 1\n", "root-commit")
    _commit_file(repo, "second.py", "s = 2\n", "second-commit")

    from core.db import get_db
    db = get_db()
    now = datetime.now().isoformat()
    project_id = "root-project"
    db.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "Root", str(repo), now)
    )
    db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?)",
        (
            project_id, "main", "main", str(repo), now,
            '{"description":"","systemDiagram":"","execution":[]}', "main"
        )
    )
    db.commit()
    db.close()

    root_tree = _tree_sha(repo, root)

    r = client.post(
        f"/api/ws/{project_id}/main/history/rename",
        json={"sha": root, "message": "renamed-root"},
    )

    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    new_shas = _local_shas(repo, "main")
    assert [_log_subject(repo, s) for s in new_shas] == ["second-commit", "renamed-root"]

    new_root = new_shas[-1]
    # The reworded root still has no parent and keeps its tree
    parent = subprocess.run(
        ["git", "rev-parse", f"{new_root}~1"],
        cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
    )
    assert parent.returncode != 0
    assert _tree_sha(repo, new_root) == root_tree


def test_rename_preserves_original_author(client, history_workspace):
    """The reworded commit keeps the original author name/email even though the
    committer becomes the current git user."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    shas = _local_shas(repo)
    middle = shas[1]
    original_author = _author(repo, middle)

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"sha": middle, "message": "author-check"},
    )

    assert r.status_code == 200
    new_shas = _local_shas(repo)
    reworded = new_shas[1]
    assert _log_subject(repo, reworded) == "author-check"
    assert _author(repo, reworded) == original_author


def test_rename_preserves_distinct_author_identity(client, history_workspace):
    """A commit authored by someone other than the committer keeps that author
    after rewording an earlier commit in the stack."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    # Add a commit authored by a distinct identity on top of the stack
    path = Path(repo) / "authored.py"
    path.write_text("a = 1\n")
    _git(repo, "add", "authored.py")
    subprocess.run(
        ["git", "commit", "-m", "authored-by-other",
         "--author=Other Dev <other@example.com>"],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )

    shas = _local_shas(repo)  # newest-first; index 0 is authored-by-other
    distinct_author = _author(repo, shas[0])
    assert distinct_author == ("Other Dev", "other@example.com")

    oldest = shas[-1]
    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"sha": oldest, "message": "reword-bottom"},
    )

    assert r.status_code == 200
    new_shas = _local_shas(repo)
    # The distinct-author commit (still newest) must keep its author after replay
    assert _author(repo, new_shas[0]) == distinct_author


def test_rename_rejects_pushed_sha(client, history_workspace):
    """Rewording a commit that is below origin/develop (already pushed) is rejected."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    pushed_sha = _rev_parse(repo, "origin/develop")

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"sha": pushed_sha, "message": "should fail"},
    )

    assert r.status_code == 400
    error = r.get_json()["error"].lower()
    assert "pushed" in error or "not found" in error


def test_rename_rejects_unknown_sha(client, history_workspace):
    """A sha not present anywhere is rejected without mutating history."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    head_before = _rev_parse(repo)

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"sha": "deadbeef" * 5, "message": "nope"},
    )

    assert r.status_code == 400
    assert _rev_parse(repo) == head_before


def test_rename_non_head_leaves_clean_linear_history(client, history_workspace):
    """After a successful non-HEAD reword the working tree is clean, there is no
    rebase/merge state, and history stays linear (every commit has one parent)."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    shas = _local_shas(repo)
    middle = shas[1]

    r = client.post(
        f"/api/ws/{pid}/develop/history/rename",
        json={"sha": middle, "message": "atomic-check"},
    )
    assert r.status_code == 200

    assert _porcelain(repo) == ""

    git_dir = Path(repo) / ".git"
    assert not (git_dir / "rebase-merge").exists()
    assert not (git_dir / "rebase-apply").exists()
    assert not (git_dir / "MERGE_HEAD").exists()

    # Linear: each local commit has exactly one parent line
    for sha in _local_shas(repo):
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", sha],
            cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
        ).stdout.split()
        assert len(parents) == 2  # the commit itself + exactly one parent


# ---------------------------------------------------------------------------
# Undo tests
# ---------------------------------------------------------------------------

def test_undo_happy_path(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    head_before = _rev_parse(repo)
    parent_before = _rev_parse(repo, "HEAD~1")

    r = client.post(f"/api/ws/{pid}/develop/history/undo")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["reset_to"] == parent_before

    # HEAD should now be the previous parent
    assert _rev_parse(repo) == parent_before

    # The changes from undone commit should be staged
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
    ).stdout
    assert status.strip()  # something staged


def test_undo_rejects_pushed_head(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    _set_origin_ref(repo, "develop")

    r = client.post(f"/api/ws/{pid}/develop/history/undo")
    assert r.status_code == 400
    assert "pushed" in r.get_json()["error"].lower()


def test_undo_rejects_dirty_tree(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]

    Path(repo, "pushed_1.py").write_text("dirty\n")
    r = client.post(f"/api/ws/{pid}/develop/history/undo")
    assert r.status_code == 400
    assert "clean" in r.get_json()["error"].lower()

    Path(repo, "pushed_1.py").write_text("x = 1\n")


def test_undo_rejects_initial_commit(client, tmp_path, clean_db):
    """A repo with a single local-unpushed commit that has no parent must reject undo.

    To satisfy _require_head_unpushed, origin/main must exist but point at an
    unrelated SHA so that origin/main..HEAD includes our orphan commit.
    """
    # Bare origin with its own unrelated commit (different history)
    bare = tmp_path / "bare_single"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare"], cwd=str(bare), check=True, capture_output=True, env=GIT_ENV)

    repo = tmp_path / "single"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "checkout", "-b", "main")
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )

    # Seed the bare origin with an unrelated commit (so origin/main exists)
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init")
    _git(seed, "checkout", "-b", "main")
    _commit_file(seed, "seed.py", "s = 0\n", "seed-commit")
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=str(seed), check=True, capture_output=True, env=GIT_ENV
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=str(seed), check=True, capture_output=True, env=GIT_ENV
    )

    # Fetch origin into our repo so origin/main exists (pointing at seed commit)
    subprocess.run(
        ["git", "fetch", "origin"],
        cwd=str(repo), check=True, capture_output=True, env=GIT_ENV
    )

    # Now make the single orphan commit on main (unrelated history)
    _commit_file(repo, "init.py", "x = 1\n", "initial commit")
    # origin/main..HEAD now includes our orphan commit (unrelated histories)

    from core.db import get_db
    db = get_db()
    now = datetime.now().isoformat()
    project_id = "single-project"
    db.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "Single", str(repo), now)
    )
    db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?)",
        (
            project_id, "main", "main", str(repo), now,
            '{"description":"","systemDiagram":"","execution":[]}', "main"
        )
    )
    db.commit()
    db.close()

    r = client.post(f"/api/ws/{project_id}/main/history/undo")
    assert r.status_code == 400
    assert "initial" in r.get_json()["error"].lower()


# ---------------------------------------------------------------------------
# Squash tests
# ---------------------------------------------------------------------------

def _local_shas(repo, source_branch="develop"):
    """Return all local-unpushed SHAs in log order (newest first)."""
    result = subprocess.run(
        ["git", "log", f"origin/{source_branch}..HEAD", "--format=%H"],
        cwd=str(repo), capture_output=True, text=True, env=GIT_ENV
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_squash_happy_path(client, history_workspace):
    """Squash the top 2 local commits."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]
    shas = _local_shas(repo)
    top2 = shas[:2]

    r = client.post(
        f"/api/ws/{pid}/develop/history/squash",
        json={"commits": top2, "message": "squashed-top-2"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["subject"] == "squashed-top-2"
    assert data["squashed"] == 2
    assert _log_subject(repo) == "squashed-top-2"

    remaining = _local_shas(repo)
    assert len(remaining) == 2  # was 3, now 2 (3rd local commit + new squash)


def test_squash_happy_path_three_commits(client, history_workspace):
    """Squash all 3 local commits into one."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]
    shas = _local_shas(repo)
    assert len(shas) == 3

    r = client.post(
        f"/api/ws/{pid}/develop/history/squash",
        json={"commits": shas, "message": "all-three-squashed"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["squashed"] == 3
    assert _log_subject(repo) == "all-three-squashed"

    remaining = _local_shas(repo)
    assert len(remaining) == 1


def test_squash_rejects_single_commit(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]
    shas = _local_shas(repo)

    r = client.post(
        f"/api/ws/{pid}/develop/history/squash",
        json={"commits": [shas[0]], "message": "one commit"},
    )
    assert r.status_code == 400
    assert "2" in r.get_json()["error"]


def test_squash_rejects_non_contiguous(client, history_workspace):
    """Select 1st and 3rd local commits, skipping 2nd — must be rejected."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]
    shas = _local_shas(repo)
    assert len(shas) == 3
    non_contiguous = [shas[0], shas[2]]  # skip shas[1]

    r = client.post(
        f"/api/ws/{pid}/develop/history/squash",
        json={"commits": non_contiguous, "message": "gap"},
    )
    assert r.status_code == 400
    assert "contiguous" in r.get_json()["error"].lower()


def test_squash_rejects_pushed_commit(client, history_workspace):
    """Including a pushed commit in selection must be rejected."""
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]
    shas = _local_shas(repo)

    # Get the pushed HEAD (one commit behind the local stack)
    pushed_head = _rev_parse(repo, "origin/develop")

    r = client.post(
        f"/api/ws/{pid}/develop/history/squash",
        json={"commits": [shas[0], pushed_head], "message": "mixing pushed"},
    )
    assert r.status_code == 400
    assert "pushed" in r.get_json()["error"].lower()


def test_squash_rejects_dirty_tree(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]
    shas = _local_shas(repo)

    Path(repo, "pushed_1.py").write_text("dirty\n")
    r = client.post(
        f"/api/ws/{pid}/develop/history/squash",
        json={"commits": shas[:2], "message": "clean first"},
    )
    assert r.status_code == 400
    assert "clean" in r.get_json()["error"].lower()

    Path(repo, "pushed_1.py").write_text("x = 1\n")


def test_squash_rejects_empty_message(client, history_workspace):
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]
    shas = _local_shas(repo)

    r = client.post(
        f"/api/ws/{pid}/develop/history/squash",
        json={"commits": shas[:2], "message": ""},
    )
    assert r.status_code == 400
    assert "message" in r.get_json()["error"].lower()


def test_squash_rejects_selection_not_including_head(client, history_workspace):
    """Squashing a contiguous range that excludes HEAD must be rejected.

    ahead_list = [C3, C2, C1]. Selecting [C2, C1] is contiguous but omits C3
    (HEAD). The reset would silently discard C3.
    """
    repo = history_workspace["working_dir"]
    pid = history_workspace["project_id"]
    shas = _local_shas(repo)
    assert len(shas) == 3  # [C3(HEAD), C2, C1]

    # Select bottom two — contiguous but excludes HEAD (shas[0])
    bottom_two = shas[1:]  # [C2, C1]

    r = client.post(
        f"/api/ws/{pid}/develop/history/squash",
        json={"commits": bottom_two, "message": "bottom squash"},
    )
    assert r.status_code == 400
    error = r.get_json()["error"].lower()
    assert "head" in error


def test_squash_rejects_when_no_origin_ref(client, tmp_path, clean_db):
    """When origin ref is absent and no local fallback ref exists, no commits are
    considered unpushed. All mutation endpoints must be rejected (fail-closed)."""
    repo = tmp_path / "noorigin"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "checkout", "-b", "feature")
    _commit_file(repo, "a.py", "x = 1\n", "commit-a")
    _commit_file(repo, "b.py", "y = 2\n", "commit-b")
    # No remote, no origin/feature ref, no local 'feature' ref to compare against
    # (we ARE on feature, so feature..HEAD yields nothing — empty set)

    from core.db import get_db
    db = get_db()
    now = datetime.now().isoformat()
    project_id = "noorigin-project"
    db.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "NoOrigin", str(repo), now)
    )
    db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?)",
        (
            project_id, "feature", "feature", str(repo), now,
            '{"description":"","systemDiagram":"","execution":[]}', "develop"
        )
    )
    db.commit()
    db.close()

    r = client.post(
        f"/api/ws/{project_id}/feature/history/rename",
        json={"message": "should be blocked"},
    )
    assert r.status_code == 400
    assert "pushed" in r.get_json()["error"].lower()


def test_ahead_of_origin_shas_uses_local_ref_fallback(tmp_path):
    """When origin/<branch> doesn't exist but a local ref does, commits between
    the local ref and HEAD are returned (not all reachable commits)."""
    import subprocess
    from routes.history import _ahead_of_origin_shas

    repo = tmp_path / "localfb"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "checkout", "-b", "develop")
    _commit_file(repo, "base.py", "x = 0\n", "base")

    # Create a local 'develop' ref pointing at the base commit,
    # then make HEAD advance beyond it on a new branch
    base_sha = _rev_parse(repo)
    _git(repo, "checkout", "-b", "feature")
    _commit_file(repo, "feat.py", "y = 1\n", "feat-commit")
    feat_sha = _rev_parse(repo)

    # No origin/feature, but local 'develop' exists as the base
    result = _ahead_of_origin_shas(str(repo), "develop")
    assert feat_sha in result
    assert base_sha not in result
