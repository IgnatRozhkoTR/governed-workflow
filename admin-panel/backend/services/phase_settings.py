"""Service for reading/writing per-level phase enablement settings.

As of sub-phase 3.6, mandatory-phase enforcement moved from this file to the
``work_mode_phases`` table. The ``basic`` system mode pins the canonical
sequence; user-defined modes may disable any phase. This module just upserts
override rows for the device / project / workspace scope chain. The phase
resolver (see ``services.phase_resolver``) layers those overrides on top of
the workspace's selected work mode.

The single residual enforcement point is the commit gate: phase ids matching
``COMMIT_GATE_PATTERN`` (``3.N.3`` and the ``3.x.3`` template) cannot be
disabled via scope overrides. Templated commit-gate phases would slip past
the work-mode baseline check otherwise.
"""
import re
from datetime import datetime

ALWAYS_ON_PHASE_IDS = frozenset()
COMMIT_GATE_PATTERN = re.compile(r"^3\.(\d+|x)\.3$")
VALID_SCOPE_TYPES = frozenset({"device", "project", "workspace"})


def is_always_on(phase_id: str) -> bool:
    """Return True only for the commit-gate phases (``3.N.3`` / ``3.x.3``).

    Work modes own the rest of the always-on contract; ``ALWAYS_ON_PHASE_IDS``
    is kept (empty) for backward import compatibility. The commit gate stays
    here because templated ids slip past the work-mode baseline check and the
    UI uses this flag to disable the toggle row.
    """
    return _is_commit_gate(phase_id)


def _is_commit_gate(phase_id: str) -> bool:
    return isinstance(phase_id, str) and bool(COMMIT_GATE_PATTERN.match(phase_id))


def _validate_scope_type(scope_type: str) -> None:
    if scope_type not in VALID_SCOPE_TYPES:
        raise ValueError(f"Invalid scope_type: {scope_type!r}")


def get_scope_settings(db, scope_type: str, scope_id: str = "") -> dict:
    _validate_scope_type(scope_type)
    rows = db.execute(
        "SELECT phase_id, enabled FROM phase_settings WHERE scope_type = ? AND scope_id = ?",
        (scope_type, scope_id),
    ).fetchall()
    return {row["phase_id"]: bool(row["enabled"]) for row in rows}


def set_scope_settings(db, scope_type: str, scope_id: str, settings: dict) -> None:
    _validate_scope_type(scope_type)
    for phase_id, enabled in settings.items():
        if not enabled and _is_commit_gate(phase_id):
            raise ValueError(
                f"Phase {phase_id} is the commit gate and cannot be disabled"
            )
    now = datetime.now().isoformat()
    try:
        for phase_id, enabled in settings.items():
            db.execute(
                "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(scope_type, scope_id, phase_id) DO UPDATE SET "
                "enabled = excluded.enabled, updated_at = excluded.updated_at",
                (scope_type, scope_id, phase_id, 1 if enabled else 0, now),
            )
    except Exception:
        db.rollback()
        raise
