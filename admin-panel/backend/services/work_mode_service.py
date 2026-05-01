"""Work modes: named, reusable phase enable/disable presets per workspace.

A work mode is a labelled bundle of ``(phase_id, enabled, position)`` rows
that decides which phases run for a workspace assigned to it. The seeded
``basic`` system mode mirrors the canonical phase registry and replaces the
hardcoded ``ALWAYS_ON_PHASE_IDS`` enforcement that used to live in
``services.phase_settings``.

User-defined modes may disable any phase; only the system origin is
immutable. Per-workspace overrides via ``phase_settings`` still apply on
top of the mode's baseline (see ``services.phase_resolver``).
"""
import re
from datetime import datetime


_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,62}$")


class WorkModeServiceError(Exception):
    """Domain error for work mode service operations.

    Codes:
        not_found         — work mode id missing.
        name_collision    — a work mode with the same name already exists.
        invalid_phases    — phases payload missing required fields or wrong type.
        invalid_name      — name does not match the allowed pattern.
        system_immutable  — attempt to mutate or delete a system-origin mode.
        not_assigned      — workspace has no work_mode_id assigned.
    """

    def __init__(self, message: str, code: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise WorkModeServiceError(
            f"Invalid work mode name '{name}'. Allowed: lowercase letters, "
            "digits, '-', '_', starting with [a-z0-9].",
            code="invalid_name",
        )


def _validate_phases(phases) -> list[dict]:
    """Coerce and validate the phases payload into a list of clean dicts."""
    if phases is None:
        return []
    if not isinstance(phases, list):
        raise WorkModeServiceError(
            "'phases' must be a list",
            code="invalid_phases",
        )

    cleaned: list[dict] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(phases):
        if not isinstance(raw, dict):
            raise WorkModeServiceError(
                f"phases[{index}] must be a dict",
                code="invalid_phases",
            )
        phase_id = raw.get("phase_id")
        if not isinstance(phase_id, str) or not phase_id.strip():
            raise WorkModeServiceError(
                f"phases[{index}].phase_id must be a non-empty string",
                code="invalid_phases",
            )
        if phase_id in seen_ids:
            raise WorkModeServiceError(
                f"phases[{index}].phase_id duplicated: {phase_id!r}",
                code="invalid_phases",
            )
        seen_ids.add(phase_id)

        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise WorkModeServiceError(
                f"phases[{index}].enabled must be a bool",
                code="invalid_phases",
            )

        position = raw.get("position", index)
        if not isinstance(position, int) or isinstance(position, bool):
            raise WorkModeServiceError(
                f"phases[{index}].position must be an int",
                code="invalid_phases",
            )

        cleaned.append({"phase_id": phase_id, "enabled": enabled, "position": position})
    return cleaned


def _row_to_mode(row, phase_rows) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "origin": row["origin"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "phases": [
            {
                "phase_id": pr["phase_id"],
                "enabled": bool(pr["enabled"]),
                "position": pr["position"],
            }
            for pr in phase_rows
        ],
    }


def _fetch_phase_rows(db, mode_id: int):
    return db.execute(
        "SELECT phase_id, enabled, position FROM work_mode_phases "
        "WHERE work_mode_id = ? ORDER BY position, phase_id",
        (mode_id,),
    ).fetchall()


def _require_mode_row(db, mode_id: int):
    row = db.execute(
        "SELECT * FROM work_modes WHERE id = ?", (mode_id,)
    ).fetchone()
    if row is None:
        raise WorkModeServiceError(
            f"Work mode {mode_id} not found",
            code="not_found",
        )
    return row


def _replace_mode_phases(db, mode_id: int, phases: list[dict]) -> None:
    db.execute("DELETE FROM work_mode_phases WHERE work_mode_id = ?", (mode_id,))
    for entry in phases:
        db.execute(
            "INSERT INTO work_mode_phases (work_mode_id, phase_id, enabled, position) "
            "VALUES (?, ?, ?, ?)",
            (
                mode_id,
                entry["phase_id"],
                1 if entry["enabled"] else 0,
                entry["position"],
            ),
        )


def create(db, name: str, description: str = "", phases: list[dict] | None = None) -> dict:
    """Insert a user-origin work mode with the given phase configuration."""
    _validate_name(name)
    cleaned_phases = _validate_phases(phases)

    existing = db.execute(
        "SELECT id FROM work_modes WHERE name = ?", (name,)
    ).fetchone()
    if existing is not None:
        raise WorkModeServiceError(
            f"Work mode named '{name}' already exists",
            code="name_collision",
        )

    now = datetime.now().isoformat()
    cursor = db.execute(
        "INSERT INTO work_modes (name, description, origin, created_at, updated_at) "
        "VALUES (?, ?, 'user', ?, ?)",
        (name, description or "", now, now),
    )
    mode_id = cursor.lastrowid
    _replace_mode_phases(db, mode_id, cleaned_phases)
    db.commit()
    return get(db, mode_id)


def list_modes(db) -> list[dict]:
    """Return every work mode with its phase rows attached."""
    rows = db.execute(
        "SELECT * FROM work_modes ORDER BY origin DESC, name"
    ).fetchall()
    return [_row_to_mode(row, _fetch_phase_rows(db, row["id"])) for row in rows]


def get(db, mode_id: int) -> dict:
    row = _require_mode_row(db, mode_id)
    return _row_to_mode(row, _fetch_phase_rows(db, mode_id))


def update(
    db,
    mode_id: int,
    name: str | None = None,
    description: str | None = None,
    phases: list[dict] | None = None,
) -> dict:
    """Sparse update for a user-origin mode. ``None`` values preserve current state."""
    row = _require_mode_row(db, mode_id)
    if row["origin"] == "system":
        raise WorkModeServiceError(
            f"Work mode '{row['name']}' is a system mode and cannot be modified.",
            code="system_immutable",
        )

    new_name = row["name"] if name is None else name
    if name is not None:
        _validate_name(name)
        if name != row["name"]:
            collision = db.execute(
                "SELECT id FROM work_modes WHERE name = ? AND id <> ?",
                (name, mode_id),
            ).fetchone()
            if collision is not None:
                raise WorkModeServiceError(
                    f"Work mode named '{name}' already exists",
                    code="name_collision",
                )

    new_description = row["description"] if description is None else description
    now = datetime.now().isoformat()

    db.execute(
        "UPDATE work_modes SET name = ?, description = ?, updated_at = ? WHERE id = ?",
        (new_name, new_description or "", now, mode_id),
    )

    if phases is not None:
        cleaned_phases = _validate_phases(phases)
        _replace_mode_phases(db, mode_id, cleaned_phases)

    db.commit()
    return get(db, mode_id)


def delete(db, mode_id: int) -> bool:
    """Delete a user-origin mode. Workspaces pointing at it fall back to NULL via FK."""
    row = _require_mode_row(db, mode_id)
    if row["origin"] == "system":
        raise WorkModeServiceError(
            f"Work mode '{row['name']}' is a system mode and cannot be deleted.",
            code="system_immutable",
        )
    db.execute("DELETE FROM work_modes WHERE id = ?", (mode_id,))
    db.commit()
    return True


def assign(db, workspace_id: int, mode_id: int) -> dict:
    """Bind a workspace to the given work mode without mutating its current phase.

    The agent stays on whatever phase column value it currently has; the new
    mode only takes effect at the next phase resolution call. Raises
    ``not_found`` when either the workspace or mode is missing.
    """
    _require_mode_row(db, mode_id)
    workspace = db.execute(
        "SELECT id, work_mode_id FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()
    if workspace is None:
        raise WorkModeServiceError(
            f"Workspace {workspace_id} not found",
            code="not_found",
        )

    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (mode_id, workspace_id),
    )
    db.commit()

    return {
        "workspace_id": workspace_id,
        "previous_mode_id": workspace["work_mode_id"],
        "mode_id": mode_id,
    }


def apply(db, workspace_id: int) -> dict:
    """Recompute the effective phase list for a workspace under its current mode.

    Returns the workspace's mode metadata plus the resolved ordered list of
    enabled phases. Does not mutate ``workspaces.phase`` — callers stay on
    their current phase until normal advancement moves them off it.
    """
    workspace = db.execute(
        "SELECT id, work_mode_id FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()
    if workspace is None:
        raise WorkModeServiceError(
            f"Workspace {workspace_id} not found",
            code="not_found",
        )

    mode_id = workspace["work_mode_id"]
    mode_name = None
    if mode_id is not None:
        mode_row = db.execute(
            "SELECT name FROM work_modes WHERE id = ?", (mode_id,)
        ).fetchone()
        if mode_row is not None:
            mode_name = mode_row["name"]

    from services.phase_resolver import resolve_for_workspace

    effective_phases = resolve_for_workspace(db, workspace_id)
    return {
        "workspace_id": workspace_id,
        "mode_id": mode_id,
        "mode_name": mode_name,
        "effective_phases": effective_phases,
    }
