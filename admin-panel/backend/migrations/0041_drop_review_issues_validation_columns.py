"""Drop the unread ``review_issues.validated`` / ``validation_reason`` columns.

Both columns were declared in the initial schema but never read or written
by any production code path; ``acceptance_criteria.validated`` /
``validation_message`` (a different feature) carries that workflow. SQLite
3.35+ supports native ``ALTER TABLE ... DROP COLUMN``, same pattern as
``0039_drop_work_modes.py``.
"""
from yoyo import step


def drop_validation_columns(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(review_issues)")
    existing = {row[1] for row in cursor.fetchall()}

    if "validated" in existing:
        cursor.execute("ALTER TABLE review_issues DROP COLUMN validated")
    if "validation_reason" in existing:
        cursor.execute("ALTER TABLE review_issues DROP COLUMN validation_reason")


step(drop_validation_columns)
