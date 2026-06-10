"""Drop the orphan prev_phase_sequence_json column from workspaces.

The column was introduced in migration 0022 without ever being read or written
by any code path. Native DROP COLUMN (SQLite >= 3.35) via PRAGMA table_info
check for idempotency — same pattern as 0039_drop_work_modes.py.
"""
from yoyo import step


def drop_prev_phase_sequence_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}

    if "prev_phase_sequence_json" in existing:
        cursor.execute("ALTER TABLE workspaces DROP COLUMN prev_phase_sequence_json")


step(drop_prev_phase_sequence_column)
