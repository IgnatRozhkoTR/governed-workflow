"""Commit history mutation routes: rename, undo, squash."""
from flask import Blueprint, jsonify, request

from core.decorators import with_workspace
from core.helpers import run_git, run_git_with, DEFAULT_SOURCE_BRANCH

bp = Blueprint("history", __name__)


def _clean_working_tree(working_dir) -> tuple:
    """Return (True, '') if working tree is clean, (False, reason) otherwise."""
    ok, output, _ = run_git(working_dir, "status", "--porcelain")
    if not ok:
        return False, "failed to check working tree status"
    if output.strip():
        return False, "working tree is not clean — commit or stash changes first"
    return True, ""


def _current_branch(working_dir):
    """Return current branch name via symbolic-ref, or None on detached HEAD."""
    ok, output, _ = run_git(working_dir, "symbolic-ref", "--short", "HEAD")
    if not ok:
        return None
    return output.strip() or None


def _ahead_of_origin_shas(working_dir, source_branch) -> list:
    """Return ordered full SHAs for commits ahead of origin/<source_branch>.

    Fail-closed behavior: when origin/<source_branch> does not exist, falls back
    to <source_branch> as a local ref. If that also doesn't exist, returns an empty
    list — no commits are considered rewritable until a reference point is established.
    """
    ok, output, _ = run_git(
        working_dir, "log", f"origin/{source_branch}..HEAD", "--format=%H"
    )
    if ok:
        return [line.strip() for line in output.splitlines() if line.strip()]

    # origin/<source_branch> may not exist; try local ref as fallback
    ok, output, _ = run_git(
        working_dir, "log", f"{source_branch}..HEAD", "--format=%H"
    )
    if ok:
        return [line.strip() for line in output.splitlines() if line.strip()]

    return []


def _is_selection_contiguous(selected_set: set, ahead_list: list) -> tuple:
    """Return (True, sorted_selection) if selected_set is a consecutive slice of ahead_list.

    ahead_list is ordered newest-first (git log order). We find the slice of
    ahead_list that matches selected_set and verify there are no gaps.
    Returns (False, []) when selection is non-contiguous or not fully in ahead_list.

    Note: contiguity alone does not guarantee safety. Callers that mutate history
    via reset must separately verify that the selection includes HEAD, to avoid
    silently discarding commits above the selected range.
    """
    indices = [i for i, sha in enumerate(ahead_list) if sha in selected_set]
    if len(indices) != len(selected_set):
        return False, []
    if not indices:
        return False, []
    if indices[-1] - indices[0] != len(indices) - 1:
        return False, []
    sorted_selection = [ahead_list[i] for i in indices]
    return True, sorted_selection


def _check_universal_preconditions(ws, working_dir):
    """Run clean-tree and branch preconditions; callers also check ahead-of-origin per action.

    Returns None if all pass, or a (response_dict, 400) tuple on failure.
    """
    is_clean, reason = _clean_working_tree(working_dir)
    if not is_clean:
        return jsonify({"ok": False, "error": reason}), 400

    current = _current_branch(working_dir)
    ws_branch = ws["branch"]
    if current is None:
        return jsonify({"ok": False, "error": "HEAD is detached — check out the workspace branch first"}), 400
    if current != ws_branch:
        return (
            jsonify({
                "ok": False,
                "error": f"HEAD is on '{current}', expected workspace branch '{ws_branch}'",
            }),
            400,
        )

    return None


def _head_sha(working_dir):
    """Return the full SHA of HEAD, or None on failure."""
    ok, output, _ = run_git(working_dir, "rev-parse", "HEAD")
    if not ok:
        return None
    return output.strip() or None


def _resolve_full_sha(working_dir, ref):
    """Resolve a commit-ish ref to its full SHA, or None if it isn't a commit.

    ``rev-parse <ref>^{commit}`` both expands an abbreviated SHA and rejects
    refs that don't point at a commit, so a bad value fails the ahead-list
    membership check rather than mutating an unintended object.
    """
    ok, output, _ = run_git(working_dir, "rev-parse", f"{ref}^{{commit}}")
    if not ok:
        return None
    return output.strip() or None


def _require_head_unpushed(working_dir, source_branch) -> tuple:
    """Verify HEAD exists and is a local-unpushed commit.

    Returns (head_sha, ahead_list, None) on success, or
    (None, None, (response, status_code)) when a guard fails.
    """
    head = _head_sha(working_dir)
    if head is None:
        return None, None, (jsonify({"ok": False, "error": "could not resolve HEAD"}), 500)

    ahead = _ahead_of_origin_shas(working_dir, source_branch)
    if head not in ahead:
        return None, None, (
            jsonify({"ok": False, "error": "HEAD commit is already pushed — cannot rewrite a pushed commit"}),
            400,
        )

    return head, ahead, None


def _commit_author_env(working_dir, sha):
    """Return GIT_AUTHOR_* env overrides preserving the original author of <sha>.

    Reads author name, email, and strict-ISO author date so a replayed commit
    keeps its original authorship even though the committer becomes the current
    git user (matching how ``git rebase`` rewrites history).
    Returns None if the commit cannot be inspected.
    """
    ok, output, _ = run_git(working_dir, "show", "-s", "--format=%an%n%ae%n%aI", sha)
    if not ok:
        return None
    lines = output.splitlines()
    if len(lines) < 3:
        return None
    return {
        "GIT_AUTHOR_NAME": lines[0],
        "GIT_AUTHOR_EMAIL": lines[1],
        "GIT_AUTHOR_DATE": lines[2],
    }


def _commit_full_message(working_dir, sha):
    """Return the full original commit message body (%B) of <sha>, or None."""
    ok, output, _ = run_git(working_dir, "show", "-s", "--format=%B", sha)
    if not ok:
        return None
    return output


def _build_commit(working_dir, sha, message, parent_sha):
    """Create a new commit object reusing <sha>'s tree and author, with <message>.

    Uses ``commit-tree`` which only writes a new object and never moves any ref,
    so a failure here leaves the repository untouched. The message is fed via
    stdin (``-F -``) so multi-line bodies and special characters are preserved
    verbatim. Returns the new commit SHA, or None on failure.
    """
    ok_tree, tree, _ = run_git(working_dir, "rev-parse", f"{sha}^{{tree}}")
    if not ok_tree:
        return None
    tree = tree.strip()

    author_env = _commit_author_env(working_dir, sha)
    if author_env is None:
        return None

    args = ["commit-tree", tree]
    if parent_sha is not None:
        args += ["-p", parent_sha]
    args += ["-F", "-"]

    ok, output, _ = run_git_with(working_dir, args, env_overrides=author_env, stdin_input=message)
    if not ok:
        return None
    return output.strip() or None


def _reword_non_head(working_dir, target, message, ahead):
    """Atomically reword an earlier (non-HEAD) local-unpushed commit.

    Rebuilds <target> with the new <message> via ``commit-tree``, then replays
    every descendant (the entries above <target> in the newest-first ``ahead``
    list, processed oldest-first) onto the new chain using each descendant's
    exact original tree — so file contents are preserved identically and no
    merge conflict is possible. All new commit objects are built first; only
    after every build succeeds is the branch advanced with a single
    ``reset --hard``. If any build fails, no ref has moved and the repo is
    untouched.

    Returns (result_dict, status_code).
    """
    ok_parent, parent_out, _ = run_git(working_dir, "rev-parse", f"{target}~1")
    parent_sha = parent_out.strip() if ok_parent else None

    reworded_sha = _build_commit(working_dir, target, message, parent_sha)
    if reworded_sha is None:
        return {"ok": False, "error": "failed to build reworded commit object"}, 500

    target_index = ahead.index(target)
    descendants_oldest_first = list(reversed(ahead[:target_index]))

    new_parent = reworded_sha
    for descendant in descendants_oldest_first:
        original_message = _commit_full_message(working_dir, descendant)
        if original_message is None:
            return {"ok": False, "error": "failed to read descendant commit message"}, 500
        new_parent = _build_commit(working_dir, descendant, original_message, new_parent)
        if new_parent is None:
            return {"ok": False, "error": "failed to replay descendant commit object"}, 500

    final_head = new_parent
    ok, _, stderr = run_git(working_dir, "reset", "--hard", final_head)
    if not ok:
        return {"ok": False, "error": f"git reset --hard failed: {stderr.strip()}"}, 500

    return {
        "ok": True,
        "sha": final_head,
        "reworded_sha": reworded_sha,
        "subject": message,
    }, 200


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/api/ws/<project_id>/<path:branch>/history/rename", methods=["POST"])
@with_workspace
def rename_commit(db, ws, project):
    """Reword a local-unpushed commit (defaults to HEAD when 'sha' is omitted)."""
    working_dir = ws["working_dir"]
    source_branch = ws["source_branch"] or DEFAULT_SOURCE_BRANCH

    failure = _check_universal_preconditions(ws, working_dir)
    if failure is not None:
        return failure

    body = request.get_json(silent=True) or {}
    message = body.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"ok": False, "error": "message must be a non-empty string"}), 400
    message = message.strip()

    requested_sha = body.get("sha")
    if requested_sha is not None and not isinstance(requested_sha, str):
        return jsonify({"ok": False, "error": "sha must be a string"}), 400

    head = _head_sha(working_dir)
    if head is None:
        return jsonify({"ok": False, "error": "could not resolve HEAD"}), 500

    ahead = _ahead_of_origin_shas(working_dir, source_branch)

    target = head if not requested_sha else _resolve_full_sha(working_dir, requested_sha)
    if target is None or target not in ahead:
        return jsonify({"ok": False, "error": "commit is already pushed or not found in local history"}), 400

    if target == head:
        ok, _, stderr = run_git(working_dir, "commit", "--amend", "-m", message)
        if not ok:
            return jsonify({"ok": False, "error": f"git commit --amend failed: {stderr.strip()}"}), 500
        new_head = _head_sha(working_dir)
        return jsonify({"ok": True, "sha": new_head, "reworded_sha": new_head, "subject": message})

    result, status = _reword_non_head(working_dir, target, message, ahead)
    return jsonify(result), status


@bp.route("/api/ws/<project_id>/<path:branch>/history/undo", methods=["POST"])
@with_workspace
def undo_commit(db, ws, project):
    """Undo HEAD commit via git reset --soft HEAD~1 (only if HEAD is local-unpushed)."""
    working_dir = ws["working_dir"]
    source_branch = ws["source_branch"] or DEFAULT_SOURCE_BRANCH

    failure = _check_universal_preconditions(ws, working_dir)
    if failure is not None:
        return failure

    head, _, guard_failure = _require_head_unpushed(working_dir, source_branch)
    if guard_failure is not None:
        return guard_failure

    ok_parent, _, _ = run_git(working_dir, "rev-parse", "HEAD~1")
    if not ok_parent:
        return jsonify({"ok": False, "error": "HEAD is the initial commit — nothing to undo"}), 400

    ok, _, stderr = run_git(working_dir, "reset", "--soft", "HEAD~1")
    if not ok:
        return jsonify({"ok": False, "error": f"git reset --soft failed: {stderr.strip()}"}), 500

    new_head = _head_sha(working_dir)
    return jsonify({"ok": True, "reset_to": new_head})


@bp.route("/api/ws/<project_id>/<path:branch>/history/squash", methods=["POST"])
@with_workspace
def squash_commits(db, ws, project):
    """Squash a contiguous selection of 2+ local-unpushed commits into one."""
    working_dir = ws["working_dir"]
    source_branch = ws["source_branch"] or DEFAULT_SOURCE_BRANCH

    failure = _check_universal_preconditions(ws, working_dir)
    if failure is not None:
        return failure

    body = request.get_json(silent=True) or {}
    commits = body.get("commits", [])
    message = body.get("message", "")

    if not isinstance(commits, list) or len(commits) < 2:
        return jsonify({"ok": False, "error": "commits must be a list of 2 or more SHAs"}), 400

    if not isinstance(message, str) or not message.strip():
        return jsonify({"ok": False, "error": "message must be a non-empty string"}), 400
    message = message.strip()

    head, ahead, guard_failure = _require_head_unpushed(working_dir, source_branch)
    if guard_failure is not None:
        return guard_failure

    ahead_set = set(ahead)
    selected_set = set(commits)

    for sha in selected_set:
        if sha not in ahead_set:
            return jsonify({"ok": False, "error": f"commit {sha[:12]} is already pushed or not found in local history"}), 400

    contiguous, sorted_selection = _is_selection_contiguous(selected_set, ahead)
    if not contiguous:
        return jsonify({"ok": False, "error": "selection must be contiguous"}), 400

    if sorted_selection[0] != head:
        return jsonify({"ok": False, "error": "selection must include the latest commit (HEAD) — commits above the selection would be lost"}), 400

    oldest_sha = sorted_selection[-1]
    parent_ref = f"{oldest_sha}~1"

    ok, _, stderr = run_git(working_dir, "reset", "--soft", parent_ref)
    if not ok:
        return jsonify({"ok": False, "error": f"git reset --soft failed: {stderr.strip()}"}), 500

    ok, _, stderr = run_git(working_dir, "commit", "-m", message)
    if not ok:
        return jsonify({"ok": False, "error": f"git commit failed: {stderr.strip()}"}), 500

    new_head = _head_sha(working_dir)
    return jsonify({"ok": True, "sha": new_head, "subject": message, "squashed": len(commits)})
