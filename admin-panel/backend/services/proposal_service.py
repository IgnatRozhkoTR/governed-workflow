"""Approval-gated text proposals emitted by reflection, memory promotion, and agents.

A proposal is a structured text record describing a recommended change (memory
note, rule update, agent/skill edit, workflow improvement). It stays in
'pending' until a human approves or rejects it. Approval is a pure status flip —
no automatic execution happens. The user reads the proposal in the admin panel
and instructs an agent how to proceed if they want.

The `type` field is metadata for human readers; it is preserved as a label and
filter key but is no longer used to route to an executor. The `payload` field is
opaque — it must be a valid JSON object but no per-type schema is enforced.

Status lifecycle:
    pending → approved (idempotent)
    pending → rejected (idempotent)
    failed/executed in older rows are legacy values from before the executor
    was removed; the column may still hold them for backward compatibility.
"""
import json
from datetime import datetime


PROPOSAL_TYPES = frozenset({
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


class ProposalServiceError(Exception):
    """Domain error for proposal service operations.

    Codes:
        not_found        — proposal id missing.
        invalid_type     — type not in PROPOSAL_TYPES (label validation only).
        invalid_payload  — payload not a dict / not JSON-serialisable, or title empty.
        invalid_state    — illegal status transition (e.g. approve after reject).
    """

    def __init__(self, message: str, code: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _row_to_dict(row) -> dict:
    record = dict(row)
    payload_raw = record.get("payload_json") or "{}"
    result_raw = record.get("result_json")
    try:
        record["payload"] = json.loads(payload_raw)
    except (TypeError, ValueError):
        record["payload"] = {}
    if result_raw:
        try:
            record["result"] = json.loads(result_raw)
        except (TypeError, ValueError):
            record["result"] = {"raw": result_raw}
    else:
        record["result"] = None
    return record


def _fetch_proposal(db, proposal_id: int):
    return db.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()


def _require_proposal(db, proposal_id: int) -> dict:
    row = _fetch_proposal(db, proposal_id)
    if row is None:
        raise ProposalServiceError(
            f"Proposal {proposal_id} not found",
            code="not_found",
        )
    return _row_to_dict(row)


def _serialize_payload(payload) -> str:
    if payload is None:
        return "{}"
    if not isinstance(payload, dict):
        raise ProposalServiceError(
            "'payload' must be a dict",
            code="invalid_payload",
        )
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ProposalServiceError(
            f"payload is not JSON-serialisable: {exc}",
            code="invalid_payload",
        ) from exc


def _validate_type(type_: str) -> None:
    if type_ not in PROPOSAL_TYPES:
        raise ProposalServiceError(
            f"Unknown proposal type '{type_}'. Allowed: {sorted(PROPOSAL_TYPES)}",
            code="invalid_type",
        )


def _require_non_empty_str(value, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProposalServiceError(
            f"'{name}' must be a non-empty string",
            code="invalid_payload",
        )


def create(
    db,
    type: str,
    title: str,
    body: str = "",
    payload: dict | None = None,
    origin: str = "agent",
    workspace_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """Insert a new pending proposal."""
    _validate_type(type)
    _require_non_empty_str(title, "title")
    payload_json = _serialize_payload(payload)
    now = datetime.utcnow().isoformat()
    cursor = db.execute(
        "INSERT INTO proposals "
        "(type, status, title, body, payload_json, origin, workspace_id, project_id, created_at) "
        "VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?)",
        (
            type,
            title.strip(),
            body or "",
            payload_json,
            origin or "agent",
            workspace_id,
            project_id,
            now,
        ),
    )
    db.commit()
    return _require_proposal(db, cursor.lastrowid)


def list_proposals(
    db,
    status: str | None = None,
    type: str | None = None,
    origin: str | None = None,
    workspace_id: int | None = None,
    project_id: int | None = None,
) -> list:
    """List proposals filtered by status / type / origin / workspace / project, newest first."""
    clauses = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if type:
        clauses.append("type = ?")
        params.append(type)
    if origin:
        clauses.append("origin = ?")
        params.append(origin)
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        f"SELECT * FROM proposals{where} ORDER BY created_at DESC, id DESC",
        params,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get(db, proposal_id: int) -> dict:
    """Fetch a single proposal by ID."""
    return _require_proposal(db, proposal_id)


def approve(db, proposal_id: int) -> dict:
    """Approve a pending proposal — pure status flip, no execution.

    The pending → approved transition is performed via a single conditional
    UPDATE so concurrent approvers see consistent state. Re-approving an
    already-approved proposal returns the current row (idempotent). Approving
    a rejected proposal raises invalid_state.
    """
    proposal = _require_proposal(db, proposal_id)
    status = proposal["status"]

    if status == "approved":
        return proposal
    if status == "rejected":
        raise ProposalServiceError(
            f"cannot approve proposal in state '{status}'",
            code="invalid_state",
            details={"current_status": status},
        )

    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE proposals SET status = 'approved', reviewed_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (now, proposal_id),
    )
    db.commit()
    return _require_proposal(db, proposal_id)


def reject(db, proposal_id: int, reason: str) -> dict:
    """Reject a pending proposal with a reason. Idempotent against rejected."""
    proposal = _require_proposal(db, proposal_id)
    status = proposal["status"]
    if status == "rejected":
        return proposal
    if status != "pending":
        raise ProposalServiceError(
            f"cannot reject proposal in state '{status}'",
            code="invalid_state",
            details={"current_status": status},
        )
    _require_non_empty_str(reason, "reason")
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE proposals SET status = 'rejected', reason = ?, reviewed_at = ? WHERE id = ?",
        (reason.strip(), now, proposal_id),
    )
    db.commit()
    return _require_proposal(db, proposal_id)


def resolve(db, proposal_id: int) -> dict:
    """Close out a proposal as rejected without re-running anything.

    Useful for clearing legacy 'failed' rows or any non-pending state aside from
    'rejected' (which is idempotent). 'pending' rows are flipped to 'rejected'
    here too so the same UI button works regardless of state.
    """
    proposal = _require_proposal(db, proposal_id)
    status = proposal["status"]
    if status == "rejected":
        return proposal
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE proposals SET status = 'rejected', reviewed_at = ? WHERE id = ?",
        (now, proposal_id),
    )
    db.commit()
    return _require_proposal(db, proposal_id)
