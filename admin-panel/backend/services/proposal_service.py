"""Proposal CRUD: create, list, and fetch agent-submitted change proposals."""
from datetime import datetime


ALLOWED_TYPES = frozenset({
    "memory_write",
    "memory_delete",
    "rule_new",
    "rule_update",
    "agent_new",
    "agent_update",
    "skill_new",
    "skill_update",
    "workflow_improvement",
})

ALLOWED_IMPLEMENTATION_KINDS = frozenset({"auto", "manual"})


class ProposalServiceError(Exception):
    """Domain error for proposal service operations."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message)
        self.code = code


def create_proposal(
    db,
    *,
    workspace_id: int,
    project_id: str,
    type: str,
    implementation_kind: str,
    title: str,
    body: str,
    payload_json: str | None = None,
    origin: str = "reflection",
    reason: str | None = None,
) -> int:
    if implementation_kind not in ALLOWED_IMPLEMENTATION_KINDS:
        raise ProposalServiceError(code="invalid_implementation_kind")
    if type not in ALLOWED_TYPES:
        raise ProposalServiceError(code="invalid_proposal_type")

    cursor = db.execute(
        "INSERT INTO proposals "
        "(workspace_id, project_id, type, implementation_kind, status, title, body, "
        "payload_json, origin, reason, created_at) "
        "VALUES (?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?)",
        (
            workspace_id,
            project_id,
            type,
            implementation_kind,
            title,
            body,
            payload_json if payload_json is not None else "{}",
            origin,
            reason,
            datetime.now().isoformat(),
        ),
    )
    db.commit()
    return cursor.lastrowid


def list_proposals(db, *, workspace_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT id, type, implementation_kind, status, title, body, payload_json, "
        "origin, workspace_id, project_id, reason, result_json, "
        "created_at, reviewed_at, executed_at "
        "FROM proposals "
        "WHERE workspace_id = ? "
        "ORDER BY created_at DESC, id DESC",
        (workspace_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_proposal(db, proposal_id: int) -> dict | None:
    row = db.execute(
        "SELECT id, type, implementation_kind, status, title, body, payload_json, "
        "origin, workspace_id, project_id, reason, result_json, "
        "created_at, reviewed_at, executed_at "
        "FROM proposals WHERE id = ?",
        (proposal_id,),
    ).fetchone()
    return dict(row) if row is not None else None
