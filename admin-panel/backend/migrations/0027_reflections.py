"""Create reflections table."""
from yoyo import step

step("""
    CREATE TABLE IF NOT EXISTS reflections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        content_md TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        session_id TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
""")

step("""
    CREATE INDEX IF NOT EXISTS idx_reflections_workspace
    ON reflections(workspace_id, created_at DESC)
""")
