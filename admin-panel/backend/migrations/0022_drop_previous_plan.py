"""Drop the legacy previous-plan versioning columns from the workspaces table.

The restore-plan feature has been removed — the prev_* columns are no longer
read or written by any code path. Drop them if they still exist.
"""
from yoyo import step

_DROP_COLUMNS = [
    "prev_plan_json",
    "prev_scope_json",
    "prev_phase",
    "prev_plan_status",
    "prev_scope_status",
]


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}

    for column_name in _DROP_COLUMNS:
        if column_name in existing:
            cursor.execute(f"ALTER TABLE workspaces DROP COLUMN {column_name}")


step(apply_step)
