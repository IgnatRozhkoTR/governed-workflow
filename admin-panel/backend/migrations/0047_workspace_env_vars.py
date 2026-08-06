"""Add a per-workspace env_vars column to the workspaces table.

Stores a dotenv-style plain-text block (KEY=VALUE lines) that the tmux respawn
loop sources into the environment every time it (re)launches Claude. The addition
checks for column existence first (idempotent).
"""
from yoyo import step


def add_env_vars_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "env_vars" not in existing:
        cursor.execute(
            "ALTER TABLE workspaces ADD COLUMN env_vars TEXT NOT NULL DEFAULT ''"
        )


def drop_env_vars_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "env_vars" in existing:
        cursor.execute("ALTER TABLE workspaces DROP COLUMN env_vars")


step(add_env_vars_column, drop_env_vars_column)
