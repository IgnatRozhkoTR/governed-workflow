"""Drop the CHECK constraint on proposals.type.

Python-layer validation in services.proposal_types.ProposalType is now the
single authoritative gate. Adding a new proposal type requires only adding a
value to the ProposalType enum — no migration needed.

SQLite cannot ALTER a CHECK constraint in place. This migration uses the
standard SQLite rebuild idiom: rename the old table, create an identical one
without the type CHECK, copy data, then drop the old table.

The status CHECK constraint is preserved — status is a lifecycle concern
controlled exclusively by the service layer and is unlikely to acquire new
values.
"""
from yoyo import step


step("""
    CREATE TABLE proposals_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
            'pending','approved','rejected','executed','failed'
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
        (id, type, status, title, body, payload_json, origin,
         workspace_id, project_id, reason, result_json,
         created_at, reviewed_at, executed_at)
    SELECT
        id, type, status, title, body, payload_json, origin,
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
