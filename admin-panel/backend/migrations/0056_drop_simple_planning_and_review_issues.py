"""Drop the simple_planning project flag and the dead review_issues table.

Simple planning has been removed; every project now uses full planning, so
projects.simple_planning (added by 0046_projects_simple_planning) goes away.
Review findings live in discussions with scope='review'; nothing reads or writes
review_issues any more. No other rows exist only for simple planning. Every step
checks the current schema first, so re-running it is a no-op.
"""
from yoyo import step


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    if "simple_planning" in {row[1] for row in cursor.fetchall()}:
        cursor.execute("ALTER TABLE projects DROP COLUMN simple_planning")
    cursor.execute("DROP TABLE IF EXISTS review_issues")


step(apply_step)
