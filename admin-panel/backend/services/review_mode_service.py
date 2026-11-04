"""Per-workspace review mode: which automatic review strategies run at phase 4.0.

Unlike :mod:`workflow_mode_service`, review mode does not write
``phase_settings`` rows or rerun the configurator chain — it only gates which
review strategies the pipeline runs (see ``services.review_pipeline_service``
and ``advance.orchestrator``), so switching it is a plain column update.
"""
from core.db import ws_field

VALID_REVIEW_MODES: tuple = ("manual", "integration", "files_integration", "full")

REVIEW_MODE_STRATEGIES: dict[str, frozenset[str]] = {
    "manual": frozenset(),
    "integration": frozenset({"integration"}),
    "files_integration": frozenset({"files", "integration"}),
    "full": frozenset({"files", "integration", "adjudication"}),
}

_DEFAULT_REVIEW_MODE = "files_integration"


def _validate_mode(mode: str) -> None:
    if mode not in VALID_REVIEW_MODES:
        raise ValueError(f"Invalid review mode: {mode!r}")


def strategies_for(ws) -> frozenset[str]:
    """Return the set of review strategies enabled for this workspace."""
    mode = ws_field(ws, "review_mode", _DEFAULT_REVIEW_MODE)
    return REVIEW_MODE_STRATEGIES.get(mode, REVIEW_MODE_STRATEGIES[_DEFAULT_REVIEW_MODE])


def _project_review_mode_default(project) -> str:
    try:
        value = project["review_mode_default"]
    except (KeyError, IndexError):
        return _DEFAULT_REVIEW_MODE
    return value or _DEFAULT_REVIEW_MODE


def resolve_default_review_mode(project, requested_mode=None) -> str:
    """Resolve the effective creation review mode from a request or project default.

    An explicit ``requested_mode`` wins (and is validated). When absent, the
    project's ``review_mode_default`` decides.
    """
    if requested_mode is not None:
        _validate_mode(requested_mode)
        return requested_mode
    return _project_review_mode_default(project)


def set_workspace_review_mode(db, ws, mode: str) -> None:
    """Persist the workspace's review mode column. Raises ``ValueError`` on an invalid mode.

    Does not write ``phase_settings`` rows or rerun the configurator chain —
    review mode only gates which review strategies the pipeline runs. The
    caller commits.
    """
    _validate_mode(mode)
    db.execute("UPDATE workspaces SET review_mode = ? WHERE id = ?", (mode, ws["id"]))
