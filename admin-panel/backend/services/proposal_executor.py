"""Type-routed executor for approved proposals.

Each proposal type maps to a single downstream service call. Failures from the
downstream service are translated into ProposalServiceError(code='execution_failed')
with the original error code and message preserved in details so the caller can
surface them to the operator.
"""
from services import agent_service
from services import improvement_service
from services import memory_service
from services import rule_service
from services import skill_service
from services.agent_service import AgentServiceError
from services.memory_provider import MemoryProviderError
from services.proposal_service import ProposalServiceError
from services.rule_service import RuleServiceError
from services.skill_service import SkillServiceError


def _wrap_execution_error(code: str, message: str, details: dict | None = None) -> ProposalServiceError:
    payload = {"underlying_code": code, "underlying_message": message}
    if details:
        payload["details"] = details
    return ProposalServiceError(
        f"execution failed: {message}",
        code="execution_failed",
        details=payload,
    )


def _require_dict(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise _wrap_execution_error(
            "invalid_payload",
            f"'{name}' must be a dict",
        )
    return value


def _require_field(payload: dict, key: str) -> object:
    if key not in payload or payload[key] in (None, ""):
        raise _wrap_execution_error(
            "invalid_payload",
            f"missing required field '{key}'",
        )
    return payload[key]


def _resolve_project_path(db, project_ref) -> str:
    """Resolve a project path by id first, then by name.

    Splitting the lookup avoids the OR-collision where a project happens to
    be named like another project's id and would shadow the intended row.
    """
    row = db.execute(
        "SELECT path FROM projects WHERE id = ?",
        (project_ref,),
    ).fetchone()
    if row is None:
        row = db.execute(
            "SELECT path FROM projects WHERE name = ?",
            (project_ref,),
        ).fetchone()
    if row is None:
        raise _wrap_execution_error(
            "not_found",
            f"project '{project_ref}' is not registered",
        )
    return row["path"]


def _execute_memory_write(db, payload: dict) -> dict:
    content = _require_field(payload, "content")
    scope = payload.get("scope") or {}
    metadata = payload.get("metadata") or {}
    try:
        return memory_service.save(content, scope, metadata)
    except MemoryProviderError as exc:
        raise _wrap_execution_error(exc.code, str(exc), exc.details)


def _execute_memory_delete(db, payload: dict) -> dict:
    memory_id = _require_field(payload, "memory_id")
    try:
        memory_service.delete(memory_id)
    except MemoryProviderError as exc:
        raise _wrap_execution_error(exc.code, str(exc), exc.details)
    return {"ok": True, "deleted_id": memory_id}


def _execute_rule_new(db, payload: dict) -> dict:
    project_ref = _require_field(payload, "project")
    project_path = _resolve_project_path(db, project_ref)
    name = _require_field(payload, "name")
    description = payload.get("description", "")
    paths = payload.get("paths") or []
    body = payload.get("body", "")
    try:
        return rule_service.create_rule(project_path, name, description, list(paths), body)
    except RuleServiceError as exc:
        raise _wrap_execution_error(exc.code, str(exc))


def _execute_rule_update(db, payload: dict) -> dict:
    project_ref = _require_field(payload, "project")
    project_path = _resolve_project_path(db, project_ref)
    name = _require_field(payload, "name")
    description = payload.get("description")
    paths = payload.get("paths")
    body = payload.get("body")
    try:
        return rule_service.update_rule(
            project_path,
            name,
            description=description,
            paths=list(paths) if paths is not None else None,
            body=body,
        )
    except RuleServiceError as exc:
        raise _wrap_execution_error(exc.code, str(exc))


def _execute_agent_new(db, payload: dict) -> dict:
    project_ref = _require_field(payload, "project")
    project_path = _resolve_project_path(db, project_ref)
    name = _require_field(payload, "name")
    description = payload.get("description", "")
    body = payload.get("body", "")
    try:
        return agent_service.create_agent(
            project_path,
            name,
            description,
            body,
            tools=payload.get("tools"),
            model=payload.get("model", "sonnet"),
            color=payload.get("color"),
        )
    except AgentServiceError as exc:
        raise _wrap_execution_error(exc.code, str(exc))


def _execute_agent_update(db, payload: dict) -> dict:
    project_ref = _require_field(payload, "project")
    project_path = _resolve_project_path(db, project_ref)
    name = _require_field(payload, "name")
    try:
        return agent_service.update_agent(
            project_path,
            name,
            description=payload.get("description"),
            body=payload.get("body"),
            tools=payload.get("tools"),
            model=payload.get("model"),
            color=payload.get("color"),
        )
    except AgentServiceError as exc:
        raise _wrap_execution_error(exc.code, str(exc))


def _execute_skill_new(db, payload: dict) -> dict:
    project_ref = _require_field(payload, "project")
    project_path = _resolve_project_path(db, project_ref)
    name = _require_field(payload, "name")
    description = payload.get("description", "")
    body = payload.get("body", "")
    try:
        return skill_service.create_skill(
            project_path,
            name,
            description,
            body,
            args=payload.get("args"),
            user_invocable=payload.get("user_invocable"),
            tools_required=payload.get("tools_required"),
        )
    except SkillServiceError as exc:
        raise _wrap_execution_error(exc.code, str(exc))


def _execute_skill_update(db, payload: dict) -> dict:
    project_ref = _require_field(payload, "project")
    project_path = _resolve_project_path(db, project_ref)
    name = _require_field(payload, "name")
    try:
        return skill_service.update_skill(
            project_path,
            name,
            description=payload.get("description"),
            body=payload.get("body"),
            args=payload.get("args"),
            user_invocable=payload.get("user_invocable"),
            tools_required=payload.get("tools_required"),
        )
    except SkillServiceError as exc:
        raise _wrap_execution_error(exc.code, str(exc))


def _execute_workflow_improvement(db, payload: dict) -> dict:
    title = _require_field(payload, "title")
    body = payload.get("body", "")
    scope = payload.get("scope", "workflow")
    context = payload.get("context")
    try:
        return improvement_service.report_improvement(db, scope, title, body, context)
    except (TypeError, ValueError) as exc:
        raise _wrap_execution_error("invalid_payload", str(exc))


_DISPATCH = {
    "memory_write": _execute_memory_write,
    "memory_delete": _execute_memory_delete,
    "rule_new": _execute_rule_new,
    "rule_update": _execute_rule_update,
    "agent_new": _execute_agent_new,
    "agent_update": _execute_agent_update,
    "skill_new": _execute_skill_new,
    "skill_update": _execute_skill_update,
    "workflow_improvement": _execute_workflow_improvement,
}


def execute(db, proposal: dict) -> dict:
    """Run the executor for the given proposal's type.

    Returns the downstream service result on success.

    Raises:
        ProposalServiceError(code='invalid_type')     — unknown proposal type.
        ProposalServiceError(code='execution_failed') — downstream call failed.
    """
    proposal_type = proposal.get("type")
    handler = _DISPATCH.get(proposal_type)
    if handler is None:
        raise ProposalServiceError(
            f"Unknown proposal type '{proposal_type}'",
            code="invalid_type",
        )
    payload = _require_dict(proposal.get("payload") or {}, "payload")
    return handler(db, payload)
