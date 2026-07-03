"""Add per-workspace workflow_mode and per-project fast_mode_default columns.

``workspaces.workflow_mode`` selects the phase set a single workspace runs:
``standard`` (the full gated workflow) or ``fast`` (a reduced set that drops
the optional research/review sub-phases). ``projects.fast_mode_default``
decides which mode a freshly created workspace inherits when the create
request does not specify one. Both additions check for column existence first
(idempotent).
"""
from yoyo import step


def add_workflow_mode_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "workflow_mode" not in existing:
        cursor.execute(
            "ALTER TABLE workspaces ADD COLUMN workflow_mode TEXT NOT NULL DEFAULT 'standard'"
        )


def drop_workflow_mode_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "workflow_mode" in existing:
        cursor.execute("ALTER TABLE workspaces DROP COLUMN workflow_mode")


def add_fast_mode_default_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "fast_mode_default" not in existing:
        cursor.execute(
            "ALTER TABLE projects ADD COLUMN fast_mode_default INTEGER NOT NULL DEFAULT 0"
        )


def drop_fast_mode_default_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "fast_mode_default" in existing:
        cursor.execute("ALTER TABLE projects DROP COLUMN fast_mode_default")


step(add_workflow_mode_column, drop_workflow_mode_column)
step(add_fast_mode_default_column, drop_fast_mode_default_column)
