"""Pull/merge request tracking per workspace, at most one row per (workspace, repo)."""
from datetime import datetime


class PrServiceError(ValueError):
    """Domain error for PR service operations."""


def _validate_url(url: str) -> None:
    if not url.startswith("http://") and not url.startswith("https://"):
        raise PrServiceError(f"Invalid PR url: {url!r}. Must start with http:// or https://")


def save_pr(db, workspace_id, url, repo_id=None, title=None) -> dict:
    """Upsert a PR for the given (workspace, repo_id) pair, including repo_id=None.

    SQLite treats NULLs as distinct under a UNIQUE constraint, so the
    single-row-per-repo invariant is enforced here instead of in the schema.
    """
    _validate_url(url)

    if repo_id is None:
        existing = db.execute(
            "SELECT id FROM workspace_prs WHERE workspace_id = ? AND repo_id IS NULL",
            (workspace_id,),
        ).fetchone()
    else:
        existing = db.execute(
            "SELECT id FROM workspace_prs WHERE workspace_id = ? AND repo_id = ?",
            (workspace_id, repo_id),
        ).fetchone()

    if existing:
        db.execute(
            "UPDATE workspace_prs SET url = ?, title = ? WHERE id = ?",
            (url, title, existing["id"]),
        )
        pr_id = existing["id"]
    else:
        cursor = db.execute(
            "INSERT INTO workspace_prs (workspace_id, repo_id, url, title, created) "
            "VALUES (?, ?, ?, ?, ?)",
            (workspace_id, repo_id, url, title, datetime.now().isoformat()),
        )
        pr_id = cursor.lastrowid

    db.commit()
    return _get_pr(db, pr_id)


def _get_pr(db, pr_id) -> dict:
    row = db.execute(
        "SELECT wp.id, wp.workspace_id, wp.repo_id, wp.url, wp.title, wp.created, "
        "pr.rel_path, pr.name "
        "FROM workspace_prs wp "
        "LEFT JOIN project_repos pr ON pr.id = wp.repo_id "
        "WHERE wp.id = ?",
        (pr_id,),
    ).fetchone()
    return dict(row)


def list_prs(db, workspace_id) -> list[dict]:
    """List PRs for a workspace, joining rel_path/name from project_repos when repo_id is set."""
    rows = db.execute(
        "SELECT wp.id, wp.workspace_id, wp.repo_id, wp.url, wp.title, wp.created, "
        "pr.rel_path, pr.name "
        "FROM workspace_prs wp "
        "LEFT JOIN project_repos pr ON pr.id = wp.repo_id "
        "WHERE wp.workspace_id = ? "
        "ORDER BY wp.created",
        (workspace_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_pr(db, workspace_id, pr_id) -> bool:
    """Delete a PR row. Returns True if a row was deleted, False if not found."""
    result = db.execute(
        "DELETE FROM workspace_prs WHERE id = ? AND workspace_id = ?",
        (pr_id, workspace_id),
    )
    db.commit()
    return result.rowcount > 0
