"""Approval-gated proposals for changes emitted by reflection and memory promotion.

Proposals execute in approval order; cross-proposal ordering is not enforced in v1.

A proposal is a structured change request (memory write, rule update, agent/skill
edit, workflow improvement) created by an agent or by automated reflection. It
stays in 'pending' until a human approves or rejects it. Approval triggers the
matching proposal_executor branch which performs the underlying mutation; on
success the proposal flips to 'executed', on failure to 'failed' with the
underlying error captured in result_json.

Re-approving an already-approved-but-still-running proposal is a no-op (returns
the current row). Re-approving an already-executed proposal raises invalid_state.
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

_TERMINAL_STATUSES = frozenset({"rejected", "executed", "failed"})


class ProposalServiceError(Exception):
    """Domain error for proposal service operations.

    Codes:
        not_found        — proposal id missing.
        invalid_type     — type not in PROPOSAL_TYPES.
        invalid_payload  — payload not a dict / not JSON-serialisable.
        invalid_state    — illegal status transition (e.g. approve after reject).
        execution_failed — downstream executor raised; underlying error in details.
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


def _mark_executed(db, proposal_id: int, result_dict: dict) -> None:
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE proposals SET status = 'executed', "
        "result_json = ?, executed_at = ? WHERE id = ?",
        (json.dumps(result_dict, ensure_ascii=False), now, proposal_id),
    )


def _mark_failed(db, proposal_id: int, error_dict: dict) -> None:
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE proposals SET status = 'failed', "
        "result_json = ?, executed_at = ? WHERE id = ?",
        (json.dumps(error_dict, ensure_ascii=False), now, proposal_id),
    )


def _mark_approved(db, proposal_id: int) -> None:
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE proposals SET status = 'approved', reviewed_at = ? WHERE id = ?",
        (now, proposal_id),
    )


def approve(db, proposal_id: int) -> dict:
    """Approve a pending proposal and run its executor.

    Idempotent: re-approving an already-approved proposal returns the current row
    without re-running the executor. Approving a terminal proposal (rejected,
    executed, failed) raises invalid_state.

    On executor success: status='executed', result_json holds the executor result.
    On executor failure: status='failed', result_json holds {underlying_code,
    underlying_message, details}.
    """
    proposal = _require_proposal(db, proposal_id)
    status = proposal["status"]

    if status == "approved":
        return proposal
    if status != "pending":
        raise ProposalServiceError(
            f"cannot approve proposal in state '{status}'",
            code="invalid_state",
            details={"current_status": status},
        )

    _mark_approved(db, proposal_id)
    db.commit()

    from services import proposal_executor
    approved = _require_proposal(db, proposal_id)
    try:
        result = proposal_executor.execute(db, approved)
    except ProposalServiceError as exc:
        error_payload = {
            "underlying_code": exc.details.get("underlying_code") or exc.code,
            "underlying_message": str(exc),
            "details": exc.details,
        }
        _mark_failed(db, proposal_id, error_payload)
        db.commit()
        return _require_proposal(db, proposal_id)

    _mark_executed(db, proposal_id, result if isinstance(result, dict) else {"value": result})
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
    """Mark a failed proposal as resolved (rejected) without re-executing.

    Useful for closing out a 'failed' proposal once the underlying issue has
    been handled out-of-band. Re-resolving an already-executed proposal raises
    invalid_state.
    """
    proposal = _require_proposal(db, proposal_id)
    status = proposal["status"]
    if status == "executed":
        raise ProposalServiceError(
            "proposal already executed",
            code="invalid_state",
            details={"current_status": status},
        )
    if status == "rejected":
        return proposal
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE proposals SET status = 'rejected', reviewed_at = ? WHERE id = ?",
        (now, proposal_id),
    )
    db.commit()
    return _require_proposal(db, proposal_id)
