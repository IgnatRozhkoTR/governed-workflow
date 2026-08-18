"""Fast mode now includes the reflection phases (5.1/5.2).

Fast workspaces created before this change may still carry workspace-scope
``phase_settings`` disable rows for ``5.1``/``5.2`` written by the old
``apply_mode_phase_settings``. Those legacy rows would keep reflection
disabled even though fast mode no longer writes them, so this migration
deletes them for every workspace whose ``workflow_mode`` is ``fast``.
"""
from datetime import datetime

from yoyo import step

_LEGACY_DISABLED_PHASE_IDS = ("5.1", "5.2")


def _fast_workspace_scope_ids(cursor):
    cursor.execute("SELECT id FROM workspaces WHERE workflow_mode = 'fast'")
    return [str(row[0]) for row in cursor.fetchall()]


def remove_fast_mode_reflection_disable_rows(conn):
    cursor = conn.cursor()
    scope_ids = _fast_workspace_scope_ids(cursor)
    if not scope_ids:
        return
    scope_placeholders = ",".join("?" for _ in scope_ids)
    phase_placeholders = ",".join("?" for _ in _LEGACY_DISABLED_PHASE_IDS)
    cursor.execute(
        f"DELETE FROM phase_settings WHERE scope_type = 'workspace' "
        f"AND phase_id IN ({phase_placeholders}) "
        f"AND scope_id IN ({scope_placeholders})",
        (*_LEGACY_DISABLED_PHASE_IDS, *scope_ids),
    )


def restore_fast_mode_reflection_disable_rows(conn):
    cursor = conn.cursor()
    scope_ids = _fast_workspace_scope_ids(cursor)
    if not scope_ids:
        return
    now = datetime.now().isoformat()
    for scope_id in scope_ids:
        for phase_id in _LEGACY_DISABLED_PHASE_IDS:
            cursor.execute(
                "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled, updated_at) "
                "VALUES ('workspace', ?, ?, 0, ?) "
                "ON CONFLICT(scope_type, scope_id, phase_id) DO UPDATE SET "
                "enabled = excluded.enabled, updated_at = excluded.updated_at",
                (scope_id, phase_id, now),
            )


step(remove_fast_mode_reflection_disable_rows, restore_fast_mode_reflection_disable_rows)
