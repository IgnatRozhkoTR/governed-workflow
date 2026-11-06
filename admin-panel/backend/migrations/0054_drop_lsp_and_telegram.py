"""Drop LSP schema, LSP setup text and Telegram leftovers.

The LSP and Telegram features have been removed. This migration drops the
lsp_instances table and the LSP columns added by 0012_lsp_support, rewrites the
Java and Kotlin system profile descriptions (0019, 0020) so they no longer tell
agents how to configure an LSP server, deletes the telegram module toggle, and
drops workspaces.channels, which only ever carried the Telegram channel flag.
Every step checks the current schema first, so re-running it is a no-op.
"""
from yoyo import step


_PROFILE_LSP_COLUMNS = [
    "lsp_command",
    "lsp_args",
    "lsp_install_check_command",
    "lsp_install_command",
    "lsp_workspace_config",
    "lsp_port",
]

_SYSTEM_PROFILE_DESCRIPTIONS = {
    "java": "Java build verification.",
    "kotlin": "Kotlin build verification using Gradle.",
}


def _drop_columns_if_present(cursor, table, columns):
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    for column_name in columns:
        if column_name in existing:
            cursor.execute(f"ALTER TABLE {table} DROP COLUMN {column_name}")


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS lsp_instances")
    _drop_columns_if_present(cursor, "verification_profiles", _PROFILE_LSP_COLUMNS)
    _drop_columns_if_present(cursor, "project_verification_profiles", ["lsp_enabled"])
    _drop_columns_if_present(cursor, "workspaces", ["channels"])

    for language, description in _SYSTEM_PROFILE_DESCRIPTIONS.items():
        cursor.execute(
            "UPDATE verification_profiles SET description = ? WHERE language = ? AND origin = 'system'",
            (description, language),
        )

    cursor.execute("DELETE FROM modules_enabled WHERE module_id = 'telegram'")


step(apply_step)
