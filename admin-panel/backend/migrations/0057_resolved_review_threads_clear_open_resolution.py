"""Give already-resolved review threads a user resolution.

Resolving a review thread used to set status='resolved' but leave
resolution='open', so the review guard kept blocking approval. Resolving now
also sets resolution='out_of_scope'; this backfills the same value on existing
resolved review roots. Re-running it is a no-op, and it skips installs where
the discussions table does not exist.
"""
from yoyo import step


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'discussions'")
    if cursor.fetchone() is None:
        return
    cursor.execute(
        "UPDATE discussions SET resolution = 'out_of_scope' "
        "WHERE scope = 'review' AND parent_id IS NULL "
        "AND status = 'resolved' AND resolution = 'open'"
    )


step(apply_step)
