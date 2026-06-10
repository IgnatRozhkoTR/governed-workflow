"""Project-level settings: simple_planning flag and future per-project booleans."""
import sqlite3


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
