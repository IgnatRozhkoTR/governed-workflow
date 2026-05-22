"""Per-project advance-mode storage for major-phase boundaries (sub-phase 3.2).

Each project may configure one of three advance modes per major phase (1–5).
The mode determines what happens when ``workspace_advance`` crosses into that
major phase:

    none    — default; no automatic action taken
    compact — compact the active session on entry
    clear   — clear the active session on entry

Absence of a row is equivalent to 'none', so no seed data is required.
"""

VALID_MODES = frozenset({"none", "compact", "clear"})
VALID_MAJOR_PHASES = frozenset({1, 2, 3, 4, 5})
_ALL_MAJOR_PHASES = (1, 2, 3, 4, 5)


class AdvanceModeServiceError(Exception):
    """Domain error for advance mode service operations.

    Codes:
        invalid_phase  — major_phase is not an integer in 1–5.
        invalid_mode   — mode is not one of 'none', 'compact', 'clear'.
    """

    def __init__(self, message: str, code: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _validate_major_phase(major_phase: int) -> None:
    if not isinstance(major_phase, int) or isinstance(major_phase, bool):
        raise AdvanceModeServiceError(
            f"major_phase must be an integer, got {type(major_phase).__name__}",
            code="invalid_phase",
        )
    if major_phase < 1 or major_phase > 5:
        raise AdvanceModeServiceError(
            f"major_phase must be between 1 and 5, got {major_phase}",
            code="invalid_phase",
        )


def _validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise AdvanceModeServiceError(
            f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}",
            code="invalid_mode",
        )


def get_mode(db, project_id: str, major_phase: int) -> str:
    """Return the advance mode for a single major phase; defaults to 'none'."""
    _validate_major_phase(major_phase)
    row = db.execute(
        "SELECT mode FROM project_advance_modes WHERE project_id = ? AND major_phase = ?",
        (project_id, major_phase),
    ).fetchone()
    return row["mode"] if row is not None else "none"


def set_modes(db, project_id: str, modes: dict[int, str]) -> None:
    """Upsert a batch of (major_phase → mode) pairs for a project.

    Unspecified phases are left unchanged. Validates all entries before
    writing so the call is all-or-nothing.
    """
    for major_phase, mode in modes.items():
        _validate_major_phase(major_phase)
        _validate_mode(mode)

    for major_phase, mode in modes.items():
        db.execute(
            "INSERT INTO project_advance_modes (project_id, major_phase, mode) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (project_id, major_phase) DO UPDATE SET mode = excluded.mode",
            (project_id, major_phase, mode),
        )
    db.commit()


def list_modes(db, project_id: str) -> dict[int, str]:
    """Return a dict with all 5 major phases, defaulting absent phases to 'none'."""
    rows = db.execute(
        "SELECT major_phase, mode FROM project_advance_modes WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    stored = {row["major_phase"]: row["mode"] for row in rows}
    return {phase: stored.get(phase, "none") for phase in _ALL_MAJOR_PHASES}
