"""Drop the dead WorkModes subsystem.

The work-modes tables and the ``workspaces.work_mode_id`` column were never
reachable from the UI, no agent referenced them, and workspace creation never
exposed them as a real option. The phase resolver now derives its baseline
directly from ``PHASE_REGISTRY`` and the scope-override layer, so the storage
is redundant.

The column drop uses ``ALTER TABLE ... DROP COLUMN`` natively (same pattern
as ``0026_drop_gate_nonce.py``); the repository targets SQLite >= 3.35.
"""
from yoyo import step


def drop_work_mode_id_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}

    if "work_mode_id" in existing:
        cursor.execute("ALTER TABLE workspaces DROP COLUMN work_mode_id")


step(drop_work_mode_id_column)
step("DROP TABLE IF EXISTS work_mode_phases")
step("DROP TABLE IF EXISTS work_modes")
