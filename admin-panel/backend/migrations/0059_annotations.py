"""Create annotations table for explanatory notes anchored to file line ranges.

repo is the attached repo's rel_path in multi-repo workspaces and '' for the
primary/single repo. anchor_text holds the exact content of lines
line_start..line_end at creation so annotations can be re-anchored after edits.
"""
from yoyo import step

step("""
    CREATE TABLE IF NOT EXISTS annotations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        repo TEXT NOT NULL DEFAULT '',
        file_path TEXT NOT NULL,
        line_start INTEGER NOT NULL,
        line_end INTEGER NOT NULL,
        text TEXT NOT NULL,
        author TEXT NOT NULL,
        anchor_text TEXT NOT NULL,
        base_commit TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
""")

step("""
    CREATE INDEX IF NOT EXISTS idx_annotations_workspace_file
    ON annotations(workspace_id, repo, file_path)
""")
