"""Project-level settings: simple_planning flag and future per-project booleans."""
import sqlite3

from services.review_mode_service import VALID_REVIEW_MODES


class ProjectSettingsError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def get_simple_planning(db: sqlite3.Connection, project_id: str) -> bool:
    """Return the simple_planning flag for the given project."""
    row = db.execute(
        "SELECT simple_planning FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise ProjectSettingsError(
            f"Project '{project_id}' not found.", code="project_not_found"
        )
    return bool(row["simple_planning"])


def set_simple_planning(db: sqlite3.Connection, project_id: str, enabled: bool) -> None:
    """Persist the simple_planning flag for the given project."""
    result = db.execute(
        "UPDATE projects SET simple_planning = ? WHERE id = ?",
        (1 if enabled else 0, project_id),
    )
    if result.rowcount == 0:
        raise ProjectSettingsError(
            f"Project '{project_id}' not found.", code="project_not_found"
        )


def get_fast_mode_default(db: sqlite3.Connection, project_id: str) -> bool:
    """Return the fast_mode_default flag for the given project."""
    row = db.execute(
        "SELECT fast_mode_default FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise ProjectSettingsError(
            f"Project '{project_id}' not found.", code="project_not_found"
        )
    return bool(row["fast_mode_default"])


def set_fast_mode_default(db: sqlite3.Connection, project_id: str, enabled: bool) -> None:
    """Persist the fast_mode_default flag for the given project."""
    result = db.execute(
        "UPDATE projects SET fast_mode_default = ? WHERE id = ?",
        (1 if enabled else 0, project_id),
    )
    if result.rowcount == 0:
        raise ProjectSettingsError(
            f"Project '{project_id}' not found.", code="project_not_found"
        )


def get_review_mode_default(db: sqlite3.Connection, project_id: str) -> str:
    """Return the review_mode_default for the given project."""
    row = db.execute(
        "SELECT review_mode_default FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise ProjectSettingsError(
            f"Project '{project_id}' not found.", code="project_not_found"
        )
    return row["review_mode_default"]


def set_review_mode_default(db: sqlite3.Connection, project_id: str, mode: str) -> None:
    """Persist the review_mode_default for the given project. Validates enum membership."""
    if mode not in VALID_REVIEW_MODES:
        raise ProjectSettingsError(
            f"Invalid review mode: {mode!r}. Must be one of {VALID_REVIEW_MODES}.",
            code="invalid_review_mode",
        )
    result = db.execute(
        "UPDATE projects SET review_mode_default = ? WHERE id = ?",
        (mode, project_id),
    )
    if result.rowcount == 0:
        raise ProjectSettingsError(
            f"Project '{project_id}' not found.", code="project_not_found"
        )
