"""Drop workspace-scoped Codex review columns added by 0015_codex_review.

The Codex review feature has been removed. This migration drops each column
IF it still exists on the workspaces table.
"""
from yoyo import step


_CODEX_COLUMNS = [
    "codex_review_enabled",
    "codex_review_status",
    "codex_review_started_at",
    "codex_review_completed_at",
    "codex_review_last_error",
]


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}

    for column_name in _CODEX_COLUMNS:
        if column_name in existing:
            cursor.execute(f"ALTER TABLE workspaces DROP COLUMN {column_name}")


step(apply_step)
