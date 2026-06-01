"""Proposal CRUD: create, list, fetch, and resolve agent-submitted change proposals."""
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

ALLOWED_STATUSES = frozenset({
    "proposed", "pending", "approved", "rejected", "executed", "failed",
})

TERMINAL_STATUSES = frozenset({"executed", "failed", "rejected"})


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


def list_proposals(
    db,
    *,
    workspace_id: int,
    implementation_kind: str | None = None,
    status: str | None = None,
) -> list[dict]:
    if implementation_kind is not None and implementation_kind not in ALLOWED_IMPLEMENTATION_KINDS:
        raise ProposalServiceError(
            code="invalid_argument",
            message=f"Unknown implementation_kind: {implementation_kind!r}",
        )
    if status is not None and status not in ALLOWED_STATUSES:
        raise ProposalServiceError(
            code="invalid_argument",
            message=f"Unknown status: {status!r}",
        )

    query = (
        "SELECT id, type, implementation_kind, status, title, body, payload_json, "
        "origin, workspace_id, project_id, reason, result_json, "
        "created_at, reviewed_at, executed_at "
        "FROM proposals WHERE workspace_id = ?"
    )
    params: list = [workspace_id]

    if implementation_kind is not None:
        query += " AND implementation_kind = ?"
        params.append(implementation_kind)
    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC, id DESC"
    rows = db.execute(query, params).fetchall()
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


def resolve_proposal(
    db,
    proposal_id: int,
    *,
    status: str,
    result_json: str | None = None,
) -> dict:
    if status not in TERMINAL_STATUSES:
        raise ProposalServiceError(
            code="invalid_argument",
            message=f"status must be one of {sorted(TERMINAL_STATUSES)}, got {status!r}",
        )

    existing = get_proposal(db, proposal_id)
    if existing is None:
        raise ProposalServiceError(code="proposal_not_found")

    now = datetime.now().isoformat()
    executed_at = now if status in {"executed", "failed"} else None
    reviewed_at = now if status == "rejected" else None

    db.execute(
        "UPDATE proposals SET status = ?, executed_at = ?, reviewed_at = ?, "
        "result_json = COALESCE(?, result_json) WHERE id = ?",
        (status, executed_at, reviewed_at, result_json, proposal_id),
    )

    return get_proposal(db, proposal_id)


def count_pending_manual_proposals(db, workspace_id: int) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM proposals "
        "WHERE workspace_id = ? AND implementation_kind = 'manual' AND status = 'proposed'",
        (workspace_id,),
    ).fetchone()
    return row["cnt"] if row else 0
