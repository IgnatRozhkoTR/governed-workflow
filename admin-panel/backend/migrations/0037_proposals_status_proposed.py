"""Expand proposals.status CHECK to include 'proposed'.

The proposal service inserts rows with status='proposed' as the initial
lifecycle state. The original CHECK was written before this state was named;
we use the standard SQLite table-rebuild idiom to widen the constraint.
"""
from yoyo import step


step("""
    CREATE TABLE proposals_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        implementation_kind TEXT NOT NULL DEFAULT 'manual',
        status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN (
            'proposed','pending','approved','rejected','executed','failed'
        )),
        title TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}',
        origin TEXT NOT NULL DEFAULT 'agent',
        workspace_id INTEGER REFERENCES workspaces(id) ON DELETE SET NULL,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        reason TEXT,
        result_json TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        reviewed_at TEXT,
        executed_at TEXT
    )
""")

step("""
    INSERT INTO proposals_new
        (id, type, implementation_kind, status, title, body, payload_json, origin,
         workspace_id, project_id, reason, result_json,
         created_at, reviewed_at, executed_at)
    SELECT
        id, type, implementation_kind, status, title, body, payload_json, origin,
        workspace_id, project_id, reason, result_json,
        created_at, reviewed_at, executed_at
    FROM proposals
""")

step("DROP TABLE proposals")

step("ALTER TABLE proposals_new RENAME TO proposals")

step("""
    CREATE INDEX IF NOT EXISTS idx_proposals_status_created
    ON proposals(status, created_at DESC)
""")

step("""
    CREATE INDEX IF NOT EXISTS idx_proposals_project_status
    ON proposals(project_id, status)
""")
