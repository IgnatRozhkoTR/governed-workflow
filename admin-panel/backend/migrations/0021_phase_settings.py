"""Per-level phase enablement settings (device / project / workspace)."""
from yoyo import step

step("""
    CREATE TABLE IF NOT EXISTS phase_settings (
        scope_type TEXT NOT NULL CHECK (scope_type IN ('device', 'project', 'workspace')),
        scope_id TEXT NOT NULL DEFAULT '',
        phase_id TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (scope_type, scope_id, phase_id)
    )
""")
