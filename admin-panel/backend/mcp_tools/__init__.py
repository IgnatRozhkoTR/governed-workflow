"""Shared infrastructure for MCP tool modules."""
import functools
import inspect
import json
import logging
import os
import re
import sqlite3
import sys

logger = logging.getLogger(__name__)
from datetime import datetime
from pathlib import Path
from typing import Literal

# Add server/ to path for shared imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP
from core.db import get_db, init_db
from core.helpers import VALID_CRITERIA_TYPES
from core.i18n import t
from services import comment_service
from services import criteria_service
from services import discussion_service
from services import improvement_service
from services import plan_service
from services import progress_service
from services import research_service
from services import scope_service
from services import verification_service

# Error categories: transient=retry OK, validation=bad input, business=domain rule,
# permission=unauthorized, not_found=entity missing.
ERROR_CATEGORY = Literal["transient", "validation", "business", "permission", "not_found"]

_VALID_ERROR_CATEGORIES = {"transient", "validation", "business", "permission", "not_found"}

# Exception classes considered genuinely transient — DB-level failures worth retrying.
# Non-transient exceptions (ProgrammingError, KeyError, TypeError, ValueError, …) must
# propagate so FastMCP sets isError=True at the protocol layer.
TRANSIENT_DB_EXCEPTIONS: tuple[type[BaseException], ...] = (
    sqlite3.OperationalError,
    sqlite3.DatabaseError,
)


def mcp_error(category: ERROR_CATEGORY, message: str, retryable: bool = False, details: dict | None = None) -> dict:
    """Build an additive error envelope for MCP tool returns.

    Preserves the legacy 'error' key (load-bearing: 30+ tests and the frontend
    read it directly) and adds structured fields required by the Claude Certified
    Architect guide (errorCategory, isRetryable, optional details).

    Use this helper at every known-error return site in MCP tool functions.
    Unexpected exceptions should still bubble up — FastMCP converts them to
    protocol-level isError=True on the CallToolResult.

    Parameters:
        category: One of transient|validation|business|permission|not_found.
            transient   — caller should retry (DB timeout, temporary network).
            validation  — caller input was malformed; retry unchanged is pointless.
            business    — domain rule prevented action (plan not approved, etc.).
            permission  — caller lacks authority.
            not_found   — a referenced entity does not exist.
        message: Human-readable message, already translated if the module uses t().
        retryable: Whether the caller should retry the call as-is. Defaults False.
        details: Optional extra context dict merged into the envelope.

    Returns:
        Dict with keys: error (message), errorCategory, isRetryable, and any details.

    Reserved keys:
        If `details` contains reserved keys (error, errorCategory, isRetryable,
        _invalid_category), they will be ignored — the structured envelope keys
        always win.
    """
    envelope = dict(details) if details else {}
    invalid = None
    if category not in _VALID_ERROR_CATEGORIES:
        invalid = category
        category = "business"
    envelope["error"] = message
    envelope["errorCategory"] = category
    envelope["isRetryable"] = bool(retryable)
    if invalid is not None:
        envelope["_invalid_category"] = invalid
    else:
        envelope.pop("_invalid_category", None)
    return envelope


def translate_service_error(
    result: dict,
    mapping: dict,
    default_category: ERROR_CATEGORY = "business",
    default_retryable: bool = False,
) -> dict:
    """Translate a service-layer ``{"error": error_key}`` dict into an mcp_error envelope.

    Collapses the dispatch ladder that appears in every tool that delegates to a
    service returning a structured error key. Preserves the original service
    message string as the envelope ``error`` value.

    Parameters:
        result: Service result containing an ``error`` key (key value used as
                lookup against ``mapping``).
        mapping: ``{error_key: (category, retryable)}`` or ``{error_key: category}``
                for a shorthand with retryable=False.
        default_category: Used when the error key is not in ``mapping``.
        default_retryable: Paired with ``default_category``.

    Returns:
        mcp_error envelope.
    """
    error_key = result.get("error", "")
    entry = mapping.get(error_key)
    if entry is None:
        category, retryable = default_category, default_retryable
    elif isinstance(entry, tuple):
        category, retryable = entry
    else:
        category, retryable = entry, False
    return mcp_error(category, error_key, retryable=retryable)


_STATUS_CODE_TO_ENVELOPE: dict[int, tuple[str, bool]] = {
    404: ("not_found", False),
    409: ("business", False),
    422: ("validation", False),
    400: ("validation", False),
}


def envelope_from_status(result: dict, status_code: int) -> dict:
    """Map an HTTP-style status code to an mcp_error category + envelope.

    Used by tools that delegate to Flask-shaped service functions returning
    ``(result_dict, status_code)``. Known codes map to specific categories;
    ``>= 500`` maps to transient/retryable; anything else falls back to business.

    Parameters:
        result: Dict whose ``error`` key holds the human-readable message.
                When absent, a synthetic ``status_<code>`` message is used.
        status_code: HTTP-style status returned by the callee.

    Returns:
        mcp_error envelope with ``details={"statusCode": status_code}`` merged in.
    """
    message = result.get("error", f"status_{status_code}")
    if status_code in _STATUS_CODE_TO_ENVELOPE:
        category, retryable = _STATUS_CODE_TO_ENVELOPE[status_code]
    elif status_code >= 500:
        category, retryable = "transient", True
    else:
        category, retryable = "business", False
    return mcp_error(category, message, retryable=retryable, details={"statusCode": status_code})


def with_global_db(func):
    """Acquire a DB connection for workspace-free tools.

    Does NOT commit — the wrapped tool MUST call ``db.commit()`` explicitly on its
    success path. Rollback and close are handled on exception. Mirrors
    with_mcp_workspace's contract: the wrapped function signature must declare
    ``db`` as its first parameter; the decorator strips it from the outer-facing
    schema via inspect.signature.

    On exception: best-effort rollback (swallowing secondary errors from an
    already-dead connection) + close, then re-raise so FastMCP sets isError=True.
    """
    sig = inspect.signature(func)
    exposed_params = [p for name, p in sig.parameters.items() if name != "db"]
    exposed_sig = sig.replace(parameters=exposed_params)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        db = get_db()
        try:
            return func(db, *args, **kwargs)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            raise
        finally:
            db.close()

    wrapper.__signature__ = exposed_sig
    return wrapper


# Initialize DB on import
init_db()


mcp = FastMCP("governed-workflow", instructions="Workspace state management for orchestrator workflow.")


def _detect_workspace():
    """Auto-detect workspace from cwd by matching working_dir in DB. Prefers active over archived."""
    cwd = os.getcwd()
    db = get_db()
    try:
        ws = db.execute(
            "SELECT * FROM workspaces WHERE working_dir = ? ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, LENGTH(working_dir) DESC, id DESC",
            (cwd,)
        ).fetchone()
        if ws:
            return ws, db.execute("SELECT * FROM projects WHERE id = ?", (ws["project_id"],)).fetchone()

        for parent in Path(cwd).parents:
            ws = db.execute(
                "SELECT * FROM workspaces WHERE working_dir = ? ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, LENGTH(working_dir) DESC, id DESC",
                (str(parent),)
            ).fetchone()
            if ws:
                return ws, db.execute("SELECT * FROM projects WHERE id = ?", (ws["project_id"],)).fetchone()

        return None, None
    finally:
        db.close()


_INJECTED_PARAMS = ("ws", "project", "db", "locale")


def with_mcp_workspace(fn):
    """Decorator that injects workspace context into MCP tool functions.

    Calls _detect_workspace(), opens a DB connection, and passes (ws, project, db, locale)
    as the first positional arguments to the wrapped function.
    Returns an error dict/list if no workspace is detected.
    Closes the DB connection in a finally block. Does NOT auto-commit.
    """
    sig = inspect.signature(fn)
    exposed_params = [p for name, p in sig.parameters.items() if name not in _INJECTED_PARAMS]
    exposed_sig = sig.replace(parameters=exposed_params)

    returns_list = sig.return_annotation is list

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        ws, project = _detect_workspace()
        if not ws:
            error = mcp_error("not_found", t("mcp.error.noWorkspace"), retryable=False, details={"reason": "no_workspace_for_path"})
            return [error] if returns_list else error

        locale = ws["locale"] or "en"
        db = get_db()
        try:
            return fn(ws, project, db, locale, *args, **kwargs)
        finally:
            db.close()

    wrapper.__signature__ = exposed_sig
    return wrapper


# Import tool modules to register @mcp.tool handlers
from mcp_tools import state  # noqa: F401, E402
from mcp_tools import advance  # noqa: F401, E402
from mcp_tools import plan_scope  # noqa: F401, E402
from mcp_tools import research  # noqa: F401, E402
from mcp_tools import comments  # noqa: F401, E402
from mcp_tools import progress  # noqa: F401, E402
from mcp_tools import criteria  # noqa: F401, E402
from mcp_tools import improvements  # noqa: F401, E402
from mcp_tools import verification  # noqa: F401, E402
from mcp_tools import rules  # noqa: F401, E402
from mcp_tools import reflection  # noqa: F401, E402
from mcp_tools import memory  # noqa: F401, E402
