"""Service for reading/writing per-level phase enablement settings."""
import re
from datetime import datetime

ALWAYS_ON_PHASE_IDS = frozenset({"0", "1.0", "2.0", "4.2", "5"})
# Commit gate: matches concrete 3.N.3 and the template id 3.x.3 so the
# template cannot be toggled off from the phase-settings UI.
COMMIT_GATE_PATTERN = re.compile(r"^3\.(\d+|x)\.3$")
VALID_SCOPE_TYPES = frozenset({"device", "project", "workspace"})


def is_always_on(phase_id: str) -> bool:
    return phase_id in ALWAYS_ON_PHASE_IDS or bool(COMMIT_GATE_PATTERN.match(phase_id))


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
        if not enabled and is_always_on(phase_id):
            raise ValueError(f"Phase {phase_id} is always-on and cannot be disabled")
    now = datetime.now().isoformat()
    for phase_id, enabled in settings.items():
        db.execute(
            "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(scope_type, scope_id, phase_id) DO UPDATE SET "
            "enabled = excluded.enabled, updated_at = excluded.updated_at",
            (scope_type, scope_id, phase_id, 1 if enabled else 0, now),
        )
