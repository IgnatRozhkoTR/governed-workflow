"""Add per-workspace review_mode and per-project review_mode_default columns.

``workspaces.review_mode`` selects which automatic review strategies run when
a workspace enters phase ``4.0``: ``manual`` (no automatic reviewers),
``integration`` (blind pair only), ``files_integration`` (per-file fan-out +
blind pair — today's behavior), or ``full`` (adds an adjudication stage).
``projects.review_mode_default`` decides which mode a freshly created
workspace inherits when the create request does not specify one. Both
additions check for column existence first (idempotent).
"""
from yoyo import step

_DEFAULT_REVIEW_MODE = "files_integration"


def add_review_mode_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "review_mode" not in existing:
        cursor.execute(
            f"ALTER TABLE workspaces ADD COLUMN review_mode TEXT NOT NULL "
            f"DEFAULT '{_DEFAULT_REVIEW_MODE}'"
        )


def drop_review_mode_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "review_mode" in existing:
        cursor.execute("ALTER TABLE workspaces DROP COLUMN review_mode")


def add_review_mode_default_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "review_mode_default" not in existing:
        cursor.execute(
            f"ALTER TABLE projects ADD COLUMN review_mode_default TEXT NOT NULL "
            f"DEFAULT '{_DEFAULT_REVIEW_MODE}'"
        )


def drop_review_mode_default_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    if "review_mode_default" in existing:
        cursor.execute("ALTER TABLE projects DROP COLUMN review_mode_default")


step(add_review_mode_column, drop_review_mode_column)
step(add_review_mode_default_column, drop_review_mode_default_column)
