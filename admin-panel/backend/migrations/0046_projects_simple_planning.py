"""Add simple_planning flag to projects table.

When ON for a project, the workflow enforces a single sub-phase plan with no
system diagrams and no acceptance criteria. The flag is a boolean stored as an
INTEGER (0/1) following the existing convention for boolean columns in SQLite.
"""
from yoyo import step


def add_simple_planning_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "simple_planning" not in existing:
        cursor.execute(
            "ALTER TABLE projects ADD COLUMN simple_planning INTEGER NOT NULL DEFAULT 0"
        )


def drop_simple_planning_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "simple_planning" in existing:
        cursor.execute("ALTER TABLE projects DROP COLUMN simple_planning")


step(add_simple_planning_column, drop_simple_planning_column)
