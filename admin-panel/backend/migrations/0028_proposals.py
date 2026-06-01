"""Create proposals table for approval-gated changes."""
from yoyo import step

step("""
    CREATE TABLE IF NOT EXISTS proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL CHECK (type IN (
            'memory_write','memory_delete',
            'rule_new','rule_update',
            'agent_new','agent_update',
            'skill_new','skill_update',
            'workflow_improvement'
        )),
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
    CREATE INDEX IF NOT EXISTS idx_proposals_status_created
    ON proposals(status, created_at DESC)
""")

step("""
    CREATE INDEX IF NOT EXISTS idx_proposals_project_status
    ON proposals(project_id, status)
""")
