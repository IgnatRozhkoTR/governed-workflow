"""Best-effort fast-forward sync of a project's local base branch.

Worktrees and non-worktree workspaces alike are always created from
``origin/<base>``; the local ``base`` branch itself is never checked out or
pulled, so it silently goes stale. These helpers fast-forward it after
workspace creation without ever risking data loss or blocking the request.
"""
import logging

from core.helpers import run_git

logger = logging.getLogger(__name__)


def branch_checked_out_anywhere(project_path, branch):
    """True if `branch` is HEAD in the main repo or any registered worktree.

    `git fetch origin <branch>:<branch>` refuses to update a checked-out
    branch's ref, so this lets us report a clean skip reason instead of
    surfacing that failure to the user.
    """
    ok_list, output, _ = run_git(project_path, "worktree", "list", "--porcelain")
    if not ok_list:
        return False
    branch_line = f"branch refs/heads/{branch}"
    return any(line.strip() == branch_line for line in output.splitlines())


def sync_local_base_branch(project_path, base):
    """Best-effort fast-forward of the local `base` branch after workspace creation.

    Worktrees and non-worktree workspaces alike are always created from
    `origin/<base>`; the local `base` branch itself is never checked out or
    pulled, so it silently goes stale. `git fetch origin <base>:<base>`
    fast-forwards a local branch that is not currently checked out and fails
    cleanly (non-zero, no partial state) when it isn't a fast-forward, so it
    is safe to attempt without ever risking data loss.
    """
    ok_local, _, _ = run_git(project_path, "rev-parse", "--verify", f"refs/heads/{base}")
    if not ok_local:
        return {"attempted": False, "updated": False, "reason": "no-local-branch"}

    if branch_checked_out_anywhere(project_path, base):
        return {"attempted": False, "updated": False, "reason": "skipped-checked-out"}

    _, before_sha, _ = run_git(project_path, "rev-parse", "--short", f"refs/heads/{base}")
    before_sha = before_sha.strip()

    ok, _, stderr = run_git(project_path, "fetch", "origin", f"{base}:{base}")
    if not ok:
        stderr = stderr or ""
        if "checked out at" in stderr:
            reason = "skipped-checked-out"
        elif "non-fast-forward" in stderr or "fast-forward" in stderr:
            reason = "not-fast-forward"
        else:
            reason = "fetch-failed"
        return {"attempted": True, "updated": False, "reason": reason}

    _, after_sha, _ = run_git(project_path, "rev-parse", "--short", f"refs/heads/{base}")
    after_sha = after_sha.strip()

    if after_sha == before_sha:
        return {"attempted": True, "updated": False, "reason": "up-to-date"}

    return {
        "attempted": True,
        "updated": True,
        "reason": f"updated-from {before_sha} to {after_sha}",
        "before": before_sha,
        "after": after_sha,
    }


def resolve_base_sync(project_path, source, source_from_origin):
    """Report whether the local `source` branch was fast-forwarded.

    Wrapped so a failure here can never block or fail workspace creation.
    """
    if not source_from_origin:
        return {"attempted": False, "updated": False, "reason": "not-remote-based"}
    try:
        return sync_local_base_branch(project_path, source)
    except Exception:
        logger.exception("Failed to sync local base branch %r after workspace creation", source)
        return {"attempted": False, "updated": False, "reason": "sync-error"}
