"""Service for reading/writing per-level phase enablement settings."""
import re
from datetime import datetime

ALWAYS_ON_PHASE_IDS = frozenset({"0", "1.0", "2.0", "4.2", "6"})
# Implementation (K=0) and Commit (K=4) steps are always-on; they form the
# mandatory skeleton of every execution sub-phase.
EXECUTION_ALWAYS_ON_PATTERN = re.compile(r"^3\.(\d+|x)\.(0|4)$")
# Whenever verification (K=1) is toggled, fix-review (K=2) must mirror it
# because K=2 is only reachable via K=1.
_VERIFICATION_STEP_PATTERN = re.compile(r"^3\.(\d+|x)\.1$")
VALID_SCOPE_TYPES = frozenset({"device", "project", "workspace"})


def is_always_on(phase_id: str) -> bool:
    return phase_id in ALWAYS_ON_PHASE_IDS or bool(EXECUTION_ALWAYS_ON_PATTERN.match(phase_id))


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


def _with_verification_mirror(settings: dict) -> dict:
    """Return a copy of settings with 3.x.2 / 3.N.2 mirroring any 3.x.1 / 3.N.1 entries.

    Fix-review (K=2) is only reachable when verification (K=1) is enabled,
    so they must always share the same enabled flag.
    """
    merged = dict(settings)
    for phase_id, enabled in settings.items():
        match = _VERIFICATION_STEP_PATTERN.match(phase_id)
        if match:
            sibling = f"3.{match.group(1)}.2"
            merged[sibling] = enabled
    return merged


def set_scope_settings(db, scope_type: str, scope_id: str, settings: dict) -> None:
    _validate_scope_type(scope_type)
    for phase_id, enabled in settings.items():
        if not enabled and is_always_on(phase_id):
            raise ValueError(f"Phase {phase_id} is always-on and cannot be disabled")
    effective = _with_verification_mirror(settings)
    now = datetime.now().isoformat()
    try:
        for phase_id, enabled in effective.items():
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


def delete_scope_settings(db, scope_type: str, scope_id: str, phase_ids) -> None:
    """Remove the scope-override rows for the given phase ids at one scope.

    A no-op when ``phase_ids`` is empty. Used to revert a scoped override set
    (e.g. clearing a workspace's fast-mode rows) back to inherited defaults.
    """
    _validate_scope_type(scope_type)
    phase_ids = tuple(phase_ids)
    if not phase_ids:
        return
    placeholders = ",".join("?" for _ in phase_ids)
    db.execute(
        f"DELETE FROM phase_settings WHERE scope_type = ? AND scope_id = ? "
        f"AND phase_id IN ({placeholders})",
        (scope_type, scope_id, *phase_ids),
    )
