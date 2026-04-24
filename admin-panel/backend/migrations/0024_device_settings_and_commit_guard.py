"""Device settings (auth + network mode) and last_confirmed_commit guard column.

Adds:
- ``device_settings`` table: generic key/value store for device-level config
  (admin_token_hash, auth_enabled, bind_host, flag:<id>). Reused by auth,
  network mode, and the legacy ``global_flags`` helper (now delegated).
- ``workspaces.last_confirmed_commit``: moving checkpoint for the commit
  progression guard on phase 3.N.4. Nullable so existing workspaces continue
  working; lazy-initialized during the next successful commit validation.

Any existing rows in ``global_flags`` are copied into ``device_settings`` under
key ``flag:<flag_id>`` with string value ``"1"``/``"0"`` so ``core.global_flags``
can keep serving the same API without reading the legacy table. The legacy
table itself is left in place to keep any out-of-tree forks happy.

Migration is idempotent so it is safe to re-run against partially migrated
databases.
"""
from yoyo import step


def apply_device_settings(conn):
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS device_settings ("
        "key TEXT PRIMARY KEY, "
        "value TEXT NOT NULL, "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )


def copy_global_flags_into_device_settings(conn):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'global_flags'"
    )
    if cursor.fetchone() is None:
        return

    cursor.execute("SELECT flag_id, enabled FROM global_flags")
    rows = cursor.fetchall()
    for flag_id, enabled in rows:
        key = f"flag:{flag_id}"
        value = "1" if int(enabled) else "0"
        cursor.execute(
            "INSERT OR IGNORE INTO device_settings (key, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            (key, value),
        )


def apply_last_confirmed_commit(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "last_confirmed_commit" not in existing:
        cursor.execute("ALTER TABLE workspaces ADD COLUMN last_confirmed_commit TEXT")


step(apply_device_settings)
step(copy_global_flags_into_device_settings)
step(apply_last_confirmed_commit)
