"""Per-project advance-mode storage keyed on boundary strings.

Each project configures an advance mode per boundary_key. The boundary_key
maps to a Phase's boundary group (e.g. "1", "2", "3.1", "3.x", "4", "5").
The mode determines what happens when workspace_advance crosses into a new
boundary group:

    none    — default; no automatic action taken
    compact — compact the active session on boundary entry
    clear   — clear the active session on boundary entry

Lookup order for get_mode_for_boundary:
  1. Exact (project_id, boundary_key) row.
  2. For "3.N" keys (N a digit), fall back to the "3.x" template row.
  3. Default "none".
"""
import re

VALID_MODES = frozenset({"none", "compact", "clear"})

DEFAULT_MODES: dict[str, str] = {
    "1": "none",
    "2": "compact",
    "3.1": "clear",
    "3.x": "compact",
    "4": "clear",
    "5": "none",
}

_EXECUTION_BOUNDARY_RE = re.compile(r'^3\.(\d+)$')


class AdvanceModeServiceError(Exception):
    """Domain error for advance mode service operations.

    Codes:
        invalid_key  — boundary_key is empty or otherwise rejected.
        invalid_mode — mode is not one of 'none', 'compact', 'clear'.
    """

    def __init__(self, message: str, code: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _validate_boundary_key(boundary_key: str) -> None:
    if not isinstance(boundary_key, str) or not boundary_key.strip():
        raise AdvanceModeServiceError(
            f"boundary_key must be a non-empty string, got {boundary_key!r}",
            code="invalid_key",
        )


def _validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise AdvanceModeServiceError(
            f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}",
            code="invalid_mode",
        )


def get_mode_for_boundary(db, project_id: str, boundary_key: str) -> str:
    """Resolve the advance mode for a boundary_key.

    Lookup order:
    1. Exact (project_id, boundary_key) match.
    2. For "3.N" execution-boundary keys, fall back to (project_id, "3.x").
    3. Default "none".
    """
    row = db.execute(
        "SELECT mode FROM project_boundary_modes WHERE project_id = ? AND boundary_key = ?",
        (project_id, boundary_key),
    ).fetchone()
    if row is not None:
        return row["mode"]

    if _EXECUTION_BOUNDARY_RE.match(boundary_key):
        template_row = db.execute(
            "SELECT mode FROM project_boundary_modes WHERE project_id = ? AND boundary_key = '3.x'",
            (project_id,),
        ).fetchone()
        if template_row is not None:
            return template_row["mode"]

    return "none"


def list_modes(db, project_id: str) -> dict[str, str]:
    """Return all configured (boundary_key -> mode) rows for the project."""
    rows = db.execute(
        "SELECT boundary_key, mode FROM project_boundary_modes WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    return {row["boundary_key"]: row["mode"] for row in rows}


def set_modes(db, project_id: str, modes: dict[str, str]) -> None:
    """Upsert a batch of (boundary_key -> mode) pairs. All-or-nothing on validation."""
    for boundary_key, mode in modes.items():
        _validate_boundary_key(boundary_key)
        _validate_mode(mode)

    for boundary_key, mode in modes.items():
        db.execute(
            "INSERT INTO project_boundary_modes (project_id, boundary_key, mode) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (project_id, boundary_key) DO UPDATE SET mode = excluded.mode",
            (project_id, boundary_key, mode),
        )
    db.commit()


def seed_default_modes(db, project_id: str) -> None:
    """Insert DEFAULT_MODES rows for a new project, skipping existing rows."""
    for boundary_key, mode in DEFAULT_MODES.items():
        db.execute(
            "INSERT OR IGNORE INTO project_boundary_modes (project_id, boundary_key, mode) "
            "VALUES (?, ?, ?)",
            (project_id, boundary_key, mode),
        )
    db.commit()
