"""Add multi-repo project support: project_type column and repo/PR registries.

``projects.project_type`` distinguishes a single-repo project (``path`` is the
repo itself) from a ``multi`` project (``path`` is a base folder containing
several git repos). ``project_repos`` registers which immediate subdirectories
of a multi project's base folder are attached repos, each with its own base
branch and an optional git-rules override. ``workspace_repos`` records, per
workspace, which registered repos are attached and where their worktrees
live. ``workspace_prs`` tracks pull/merge request URLs per workspace, one row
per repo (or a single project-wide row when ``repo_id`` is NULL).
"""
from yoyo import step


def add_project_type_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "project_type" not in existing:
        cursor.execute(
            "ALTER TABLE projects ADD COLUMN project_type TEXT NOT NULL DEFAULT 'single'"
        )


def drop_project_type_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "project_type" in existing:
        cursor.execute("ALTER TABLE projects DROP COLUMN project_type")


step(add_project_type_column, drop_project_type_column)

step(
    """
    CREATE TABLE IF NOT EXISTS project_repos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        rel_path TEXT NOT NULL,
        name TEXT NOT NULL,
        base_branch TEXT NOT NULL DEFAULT 'develop',
        enabled INTEGER NOT NULL DEFAULT 1,
        git_rules_override TEXT,
        registered TEXT NOT NULL,
        UNIQUE(project_id, rel_path)
    )
    """,
    "DROP TABLE IF EXISTS project_repos",
)

step(
    "CREATE INDEX IF NOT EXISTS idx_project_repos_project_id ON project_repos(project_id)",
    "DROP INDEX IF EXISTS idx_project_repos_project_id",
)

step(
    """
    CREATE TABLE IF NOT EXISTS workspace_repos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        repo_id INTEGER NOT NULL REFERENCES project_repos(id) ON DELETE CASCADE,
        branch TEXT NOT NULL,
        worktree_path TEXT NOT NULL,
        attached TEXT NOT NULL,
        UNIQUE(workspace_id, repo_id)
    )
    """,
    "DROP TABLE IF EXISTS workspace_repos",
)

step(
    "CREATE INDEX IF NOT EXISTS idx_workspace_repos_workspace_id ON workspace_repos(workspace_id)",
    "DROP INDEX IF EXISTS idx_workspace_repos_workspace_id",
)

step(
    """
    CREATE TABLE IF NOT EXISTS workspace_prs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        repo_id INTEGER REFERENCES project_repos(id) ON DELETE CASCADE,
        url TEXT NOT NULL,
        title TEXT,
        created TEXT NOT NULL
    )
    """,
    "DROP TABLE IF EXISTS workspace_prs",
)

step(
    "CREATE INDEX IF NOT EXISTS idx_workspace_prs_workspace_id ON workspace_prs(workspace_id)",
    "DROP INDEX IF EXISTS idx_workspace_prs_workspace_id",
)
