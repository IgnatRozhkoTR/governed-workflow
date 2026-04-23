"""Shared infrastructure for MCP tool modules."""
import functools
import inspect
import json
import logging
import os
import re
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
    """
    if category not in _VALID_ERROR_CATEGORIES:
        envelope = {
            "error": message,
            "errorCategory": "business",
            "isRetryable": retryable,
            "_invalid_category": category,
        }
    else:
        envelope = {
            "error": message,
            "errorCategory": category,
            "isRetryable": retryable,
        }
    if details:
        envelope.update(details)
    return envelope


def with_global_db(func):
    """Inject a SQLAlchemy session into a tool function that doesn't need a workspace.

    Replaces the 10-times-duplicated `db = get_db(); try: ... finally: db.close()`
    block across improvement/profile/etc. tools. Mirrors with_mcp_workspace's contract:
    function signature must accept `db` as its first parameter AFTER the MCP-visible
    params; the decorator strips it from the outer-facing schema via inspect.signature.

    On exception: rollback + close, then re-raise so FastMCP sets isError=True.
    On success: commit if the returned dict does NOT have 'error' key; close.
    """
    sig = inspect.signature(func)
    exposed_params = [p for name, p in sig.parameters.items() if name != "db"]
    exposed_sig = sig.replace(parameters=exposed_params)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        db = get_db()
        try:
            result = func(db, *args, **kwargs)
            if isinstance(result, dict) and "error" not in result:
                db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    wrapper.__signature__ = exposed_sig
    return wrapper


# Initialize DB on import
init_db()


mcp = FastMCP("workspace", instructions="Workspace state management for orchestrator workflow.")


def _detect_workspace():
    """Auto-detect workspace from cwd by matching working_dir in DB. Prefers active over archived."""
    cwd = os.getcwd()
    db = get_db()
    try:
        ws = db.execute(
            "SELECT * FROM workspaces WHERE working_dir = ? ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC",
            (cwd,)
        ).fetchone()
        if ws:
            return ws, db.execute("SELECT * FROM projects WHERE id = ?", (ws["project_id"],)).fetchone()

        for parent in Path(cwd).parents:
            ws = db.execute(
                "SELECT * FROM workspaces WHERE working_dir = ? ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC",
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
