"""Multi-repo project registry: subdirectory scanning, repo CRUD, and git-rules resolution."""
import os
import shutil
from datetime import datetime
from pathlib import Path

from core.helpers import run_git
from services import base_sync_service
from services.git_rules_service import git_rules_path, migrate_legacy_git_rules

UNSET = object()


class RepoServiceError(ValueError):
    """Domain error for repo attach operations, carrying a short error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _has_git_marker(path: Path) -> bool:
    """Return True if path contains a .git entry (dir for a normal repo, file for a worktree)."""
    git_entry = path / ".git"
    return git_entry.is_dir() or git_entry.is_file()


def scan_repos(base_path) -> list[dict]:
    """List immediate subdirectories of base_path that are git repositories.

    Skips dotdirs and node_modules. Each candidate reports its current branch
    on a best-effort basis (empty scan on I/O error, None branch on git
    failure) so a partially-unreadable base folder never raises.
    """
    root = Path(base_path)
    if not root.is_dir():
        return []

    names = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not entry.is_dir():
                    continue
                if entry.name.startswith(".") or entry.name == "node_modules":
                    continue
                if _has_git_marker(Path(entry.path)):
                    names.append(entry.name)
    except OSError:
        return []

    candidates = []
    for rel_path in sorted(names):
        ok, branch, _ = run_git(str(root / rel_path), "rev-parse", "--abbrev-ref", "HEAD")
        candidates.append({
            "rel_path": rel_path,
            "name": rel_path,
            "current_branch": branch.strip() if ok else None,
        })
    return candidates


def _format_repo_summary(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "rel_path": row["rel_path"],
        "name": row["name"],
        "base_branch": row["base_branch"],
        "enabled": bool(row["enabled"]),
        "has_rules_override": bool(row["git_rules_override"]),
        "registered": row["registered"],
    }


def _format_repo_full(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "rel_path": row["rel_path"],
        "name": row["name"],
        "base_branch": row["base_branch"],
        "enabled": bool(row["enabled"]),
        "git_rules_override": row["git_rules_override"],
        "registered": row["registered"],
    }


def list_repos(db, project_id) -> list[dict]:
    """List registered repos for a project, without override text."""
    rows = db.execute(
        "SELECT id, project_id, rel_path, name, base_branch, enabled, git_rules_override, registered "
        "FROM project_repos WHERE project_id = ? ORDER BY rel_path",
        (project_id,),
    ).fetchall()
    return [_format_repo_summary(row) for row in rows]


def get_repo(db, project_id, repo_id) -> dict | None:
    """Fetch a single registered repo, including its git-rules override text."""
    row = db.execute(
        "SELECT id, project_id, rel_path, name, base_branch, enabled, git_rules_override, registered "
        "FROM project_repos WHERE project_id = ? AND id = ?",
        (project_id, repo_id),
    ).fetchone()
    return _format_repo_full(row) if row is not None else None


def set_repos(db, project_id, repos: list[dict]) -> None:
    """Replace a project's repo registry from a `[{rel_path, base_branch}]` selection.

    Upserts by `rel_path`, preserving the existing id and git_rules_override
    for rows that are kept, and deletes registered repos absent from `repos`.
    """
    existing_rows = db.execute(
        "SELECT id, rel_path FROM project_repos WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    existing_by_rel_path = {row["rel_path"]: row["id"] for row in existing_rows}

    incoming_rel_paths = {repo["rel_path"] for repo in repos}
    now = datetime.now().isoformat()

    for repo in repos:
        rel_path = repo["rel_path"]
        base_branch = repo["base_branch"]
        name = Path(rel_path).name
        if rel_path in existing_by_rel_path:
            db.execute(
                "UPDATE project_repos SET name = ?, base_branch = ? WHERE id = ?",
                (name, base_branch, existing_by_rel_path[rel_path]),
            )
        else:
            db.execute(
                "INSERT INTO project_repos (project_id, rel_path, name, base_branch, registered) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, rel_path, name, base_branch, now),
            )

    for rel_path in set(existing_by_rel_path) - incoming_rel_paths:
        db.execute("DELETE FROM project_repos WHERE id = ?", (existing_by_rel_path[rel_path],))

    db.commit()


def update_repo(db, project_id, repo_id, *, base_branch=None, git_rules_override=UNSET) -> dict | None:
    """Partially update a registered repo. Returns the updated row, or None if not found.

    `git_rules_override` defaults to the `UNSET` sentinel so callers can
    distinguish "not provided" (leave unchanged) from an explicit `None`
    (clear the override).
    """
    updates = []
    params = []
    if base_branch is not None:
        updates.append("base_branch = ?")
        params.append(base_branch)
    if git_rules_override is not UNSET:
        updates.append("git_rules_override = ?")
        params.append(git_rules_override)

    if updates:
        params.extend([project_id, repo_id])
        db.execute(
            f"UPDATE project_repos SET {', '.join(updates)} WHERE project_id = ? AND id = ?",
            params,
        )
        db.commit()

    return get_repo(db, project_id, repo_id)


def resolve_git_rules(db, project, repo_row) -> str:
    """Resolve effective git rules text: repo override if non-empty, else project rules."""
    override = repo_row["git_rules_override"]
    if override:
        return override

    project_path = project["path"]
    migrate_legacy_git_rules(project_path)
    rules_path = git_rules_path(project_path)
    if rules_path.exists():
        return rules_path.read_text()
    return ""


def attach_repo(db, ws, project, repo_row) -> dict:
    """Attach a registered repo to a multi-repo workspace: worktree + branch + DB row.

    Mirrors ``_setup_worktree_workspace``'s stale-path recovery, but only deletes
    the stale ticket branch when it isn't checked out anywhere else (a repo's
    worktree may legitimately be recreated after an archive while the branch
    still holds unpushed work in another worktree).

    Raises RepoServiceError on validation or git failures.
    """
    if project["project_type"] != "multi":
        raise RepoServiceError("not_multi_project", "Project is not a multi-repo project")
    if not repo_row["enabled"]:
        raise RepoServiceError("repo_disabled", f"Repo '{repo_row['rel_path']}' is disabled")
    if ws["status"] != "active":
        raise RepoServiceError("workspace_not_active", "Workspace is not active")

    existing = db.execute(
        "SELECT id FROM workspace_repos WHERE workspace_id = ? AND repo_id = ?",
        (ws["id"], repo_row["id"]),
    ).fetchone()
    if existing:
        raise RepoServiceError(
            "already_attached", f"Repo '{repo_row['rel_path']}' is already attached to this workspace"
        )

    repo_abs = Path(project["path"]) / repo_row["rel_path"]

    has_remote, remotes, _ = run_git(str(repo_abs), "remote")
    if has_remote and remotes.strip():
        run_git(str(repo_abs), "fetch", "origin")

    base_branch = repo_row["base_branch"]
    source_ref = f"origin/{base_branch}"
    ok, _, _ = run_git(str(repo_abs), "rev-parse", "--verify", source_ref)
    source_from_origin = ok
    if not ok:
        ok, _, _ = run_git(str(repo_abs), "rev-parse", "--verify", base_branch)
        if not ok:
            raise RepoServiceError(
                "base_branch_not_found",
                f"Base branch '{base_branch}' not found locally or on remote for repo '{repo_row['rel_path']}'",
            )
        source_ref = base_branch

    base_sync = base_sync_service.resolve_base_sync(str(repo_abs), base_branch, source_from_origin)

    branch = ws["branch"]
    worktree_path = Path(ws["working_dir"]) / repo_row["rel_path"]
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    run_git(str(repo_abs), "worktree", "prune")

    if worktree_path.exists():
        run_git(str(repo_abs), "worktree", "remove", str(worktree_path), "--force")
        if not base_sync_service.branch_checked_out_anywhere(str(repo_abs), branch):
            run_git(str(repo_abs), "branch", "-D", branch)
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
        run_git(str(repo_abs), "worktree", "prune")

    ok_branch, _, _ = run_git(str(repo_abs), "rev-parse", "--verify", f"refs/heads/{branch}")
    if ok_branch:
        ok, _, stderr = run_git(str(repo_abs), "worktree", "add", str(worktree_path), branch)
    else:
        ok, _, stderr = run_git(str(repo_abs), "worktree", "add", str(worktree_path), "-b", branch, source_ref)

    if not ok:
        raise RepoServiceError(
            "worktree_add_failed",
            f"git worktree add failed for repo '{repo_row['rel_path']}': {stderr}",
        )

    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO workspace_repos (workspace_id, repo_id, branch, worktree_path, attached) "
        "VALUES (?, ?, ?, ?, ?)",
        (ws["id"], repo_row["id"], branch, str(worktree_path), now),
    )
    db.commit()

    return {
        "repo_id": repo_row["id"],
        "rel_path": repo_row["rel_path"],
        "name": repo_row["name"],
        "branch": branch,
        "worktree_path": str(worktree_path),
        "base_sync": base_sync,
    }


def list_attached(db, workspace_id) -> list[dict]:
    """List repos attached to a workspace, joining rel_path/name/base_branch from the registry."""
    rows = db.execute(
        "SELECT pr.rel_path, pr.name, wr.branch, wr.worktree_path, pr.base_branch "
        "FROM workspace_repos wr "
        "JOIN project_repos pr ON pr.id = wr.repo_id "
        "WHERE wr.workspace_id = ? "
        "ORDER BY pr.rel_path",
        (workspace_id,),
    ).fetchall()
    return [dict(row) for row in rows]
