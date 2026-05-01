"""Service for reading/writing per-level phase enablement settings.

As of sub-phase 3.6, mandatory-phase enforcement moved from this file to the
``work_mode_phases`` table. The ``basic`` system mode pins the canonical
sequence; user-defined modes may disable any phase. This module no longer
hardcodes always-on phase ids — it just upserts override rows for the
device / project / workspace scope chain. The phase resolver (see
``services.phase_resolver``) layers those overrides on top of the workspace's
selected work mode.
"""
from datetime import datetime

ALWAYS_ON_PHASE_IDS = frozenset()
VALID_SCOPE_TYPES = frozenset({"device", "project", "workspace"})


def is_always_on(phase_id: str) -> bool:
    """Always returns ``False``: mandatory phases are now governed by work modes.

    The constant ``ALWAYS_ON_PHASE_IDS`` is kept (empty) so callers that import
    it for legacy reasons keep working without raising ``ImportError``.
    """
    del phase_id
    return False


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
