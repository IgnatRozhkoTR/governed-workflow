"""Drop the gate_nonce column from the workspaces table.

Gate nonces have been fully removed — admin-token middleware authenticates
approve/reject calls, so no per-request token is stored or consulted. This
migration removes the obsolete column.

The DROP is gated on a ``PRAGMA table_info(workspaces)`` check so the
migration is idempotent and safe to re-run against partially migrated
databases. SQLite >= 3.35 supports ALTER TABLE DROP COLUMN natively;
earlier versions would require a full rebuild, but the repository targets
modern SQLite so the native form is used.
"""
from yoyo import step


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}

    if "gate_nonce" in existing:
        cursor.execute("ALTER TABLE workspaces DROP COLUMN gate_nonce")


step(apply_step)
