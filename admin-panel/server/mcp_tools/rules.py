"""MCP tools for managing per-project rule files under .claude/rules/."""
from typing import Annotated, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import TRANSIENT_DB_EXCEPTIONS, mcp, mcp_error, with_global_db
from core.i18n import t
from services import rule_service
from services.rule_service import RuleServiceError


def _resolve_project_path(db, project: str):
    row = db.execute(
        "SELECT id, path FROM projects WHERE id = ? OR name = ?",
        (project, project),
    ).fetchone()
    if row is None:
        return None
    return row["path"]


def _translate_rule_error(exc: RuleServiceError, name: str, locale: str = "en") -> dict:
    if exc.code == "not_found":
        return mcp_error("not_found", t("mcp.error.ruleNotFound", locale, name=name), retryable=False)
    if exc.code == "already_exists":
        return mcp_error("business", t("mcp.error.ruleAlreadyExists", locale, name=name), retryable=False)
    if exc.code == "default_immutable":
        return mcp_error("business", t("mcp.error.ruleDefaultImmutable", locale, name=name), retryable=False)
    if exc.code == "invalid_name":
        return mcp_error("validation", t("mcp.error.ruleInvalidName", locale, name=name), retryable=False)
    if exc.code == "invalid_frontmatter":
        return mcp_error(
            "validation",
            t("mcp.error.ruleInvalidFrontmatter", locale, name=name, details=str(exc)),
            retryable=False,
        )
    return mcp_error("business", str(exc), retryable=False)


def _project_not_found_error(project: str, locale: str = "en") -> dict:
    return mcp_error(
        "not_found",
        t("mcp.error.projectNotFound", locale),
        retryable=False,
        details={"project": project},
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="List rules",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def rule_list(
    db,
    project: Annotated[str, Field(description="Project ID or name registered in the admin panel.", min_length=1)],
) -> list:
    """List all rules for a project.

    Purpose
      Return every rule file under <project>/.claude/rules/ with metadata only.
      Default rules are marked with source='default'; user-created rules with
      source='user'. Defaults cannot be modified or deleted.

    Returns
      List of {name, description, paths, source[, error]}. Malformed files
      surface with an 'error' field instead of crashing.

    Errors
      not_found  — project is not registered.
      transient  — DB failure; caller should retry.
    """
    try:
        project_path = _resolve_project_path(db, project)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return [mcp_error("transient", str(exc), retryable=True)]
    if project_path is None:
        return [_project_not_found_error(project)]
    return rule_service.list_rules(project_path)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get rule",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def rule_get(
    db,
    project: Annotated[str, Field(description="Project ID or name registered in the admin panel.", min_length=1)],
    name: Annotated[str, Field(description="Rule name (filename stem, without .md). Allowed: [a-z0-9-_], starting with [a-z0-9].", min_length=1)],
) -> dict:
    """Get a single rule with full body and frontmatter.

    Returns
      {name, description, paths, body, source}

    Errors
      not_found   — project or rule missing.
      validation  — rule name has disallowed characters or invalid frontmatter.
      transient   — DB failure; caller should retry.
    """
    try:
        project_path = _resolve_project_path(db, project)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
    if project_path is None:
        return _project_not_found_error(project)
    try:
        return rule_service.get_rule(project_path, name)
    except RuleServiceError as exc:
        return _translate_rule_error(exc, name)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create rule",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_global_db
def rule_create(
    db,
    project: Annotated[str, Field(description="Project ID or name registered in the admin panel.", min_length=1)],
    name: Annotated[str, Field(description="New rule name (filename stem). Allowed: [a-z0-9-_], starting with [a-z0-9], max 63 chars.", min_length=1)],
    description: Annotated[str, Field(description="Short human summary of the rule.")],
    paths: Annotated[list[str], Field(description="Glob patterns that trigger auto-loading, e.g. ['**/*.py', 'src/**/*.ts'].")],
    body: Annotated[str, Field(description="Markdown body of the rule (everything after the YAML frontmatter).")],
) -> dict:
    """Create a new user rule file at <project>/.claude/rules/<name>.md.

    Purpose
      Add a new rule with YAML frontmatter (name, description, paths) and a
      markdown body. Default rules cannot be created through this API.

    Returns
      {name, description, paths, body, source='user'}

    Errors
      not_found         — project is not registered.
      business          — rule name collides with an existing user rule
                          (already_exists) or is a protected default
                          (default_immutable).
      validation        — rule name fails the [a-z0-9-_] / leading-alnum check.
      transient         — DB failure; caller should retry.
    """
    try:
        project_path = _resolve_project_path(db, project)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
    if project_path is None:
        return _project_not_found_error(project)
    try:
        return rule_service.create_rule(project_path, name, description, list(paths or []), body)
    except RuleServiceError as exc:
        return _translate_rule_error(exc, name)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update rule",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_global_db
def rule_update(
    db,
    project: Annotated[str, Field(description="Project ID or name registered in the admin panel.", min_length=1)],
    name: Annotated[str, Field(description="Rule name (filename stem, without .md).", min_length=1)],
    description: Annotated[Optional[str], Field(description="Updated description. None = keep current.")] = None,
    paths: Annotated[Optional[list[str]], Field(description="Updated glob patterns. None = keep current. Empty list clears.")] = None,
    body: Annotated[Optional[str], Field(description="Updated markdown body. None = keep current.")] = None,
) -> dict:
    """Update an existing user rule. Partial updates are supported.

    Purpose
      Only fields explicitly provided (non-None) are updated. Default rules
      cannot be modified.

    Returns
      {name, description, paths, body, source='user'}

    Errors
      not_found    — project or rule missing.
      business     — rule is a protected default (default_immutable).
      validation   — rule name fails validation or frontmatter is malformed.
      transient    — DB failure; caller should retry.
    """
    try:
        project_path = _resolve_project_path(db, project)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
    if project_path is None:
        return _project_not_found_error(project)
    try:
        return rule_service.update_rule(
            project_path,
            name,
            description=description,
            paths=list(paths) if paths is not None else None,
            body=body,
        )
    except RuleServiceError as exc:
        return _translate_rule_error(exc, name)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete rule",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=True,
    )
)
@with_global_db
def rule_delete(
    db,
    project: Annotated[str, Field(description="Project ID or name registered in the admin panel.", min_length=1)],
    name: Annotated[str, Field(description="Rule name (filename stem, without .md).", min_length=1)],
) -> dict:
    """Delete a user rule file.

    Purpose
      Remove <project>/.claude/rules/<name>.md. Default rules cannot be
      deleted. Deleting an already-missing user rule returns not_found.

    Returns
      {ok: True, deleted_name: str}

    Errors
      not_found    — project or rule missing.
      business     — rule is a protected default (default_immutable).
      validation   — rule name fails validation.
      transient    — DB failure; caller should retry.
    """
    try:
        project_path = _resolve_project_path(db, project)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
    if project_path is None:
        return _project_not_found_error(project)
    try:
        rule_service.delete_rule(project_path, name)
    except RuleServiceError as exc:
        return _translate_rule_error(exc, name)
    return {"ok": True, "deleted_name": name}
