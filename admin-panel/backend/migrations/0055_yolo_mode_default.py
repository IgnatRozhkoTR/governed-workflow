"""Add per-project yolo_mode_default column.

``projects.yolo_mode_default`` makes every new workspace in the project start
with yolo_mode enabled. Every step checks the current schema first, so
re-running it is a no-op.
"""
from yoyo import step


def add_yolo_mode_default_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "yolo_mode_default" not in existing:
        cursor.execute(
            "ALTER TABLE projects ADD COLUMN yolo_mode_default INTEGER NOT NULL DEFAULT 0"
        )


def drop_yolo_mode_default_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "yolo_mode_default" in existing:
        cursor.execute("ALTER TABLE projects DROP COLUMN yolo_mode_default")


step(add_yolo_mode_default_column, drop_yolo_mode_default_column)
