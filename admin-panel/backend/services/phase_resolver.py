"""Resolve effective enabled-phase set across work mode + scope overrides.

Order of precedence (lowest to highest):
    1. ``work_mode_phases`` rows for the workspace's assigned mode supply the
       baseline. Phases listed with ``enabled=0`` are disabled; phases listed
       with ``enabled=1`` are enabled. Phases NOT listed in the mode default
       to enabled, so plan-expanded ``3.N.K`` execution phases still appear
       even though only canonical (non-templated) ids are seeded into modes.
    2. ``phase_settings`` rows at scope ``device``, then ``project``, then
       ``workspace`` may flip individual ids on or off.

The legacy hardcoded ALWAYS_ON enforcement was removed in sub-phase 3.6:
mandatory phases now live in ``work_mode_phases`` rows.
"""
from services.phase_settings import get_scope_settings

_SCOPE_PRECEDENCE = ("device", "project", "workspace")


def _apply_scope_overrides(db, workspace_id, project_id, enabled: set, universe: set) -> None:
    """Apply per-level phase-settings rows in precedence order. Mutates ``enabled`` in place."""
    scope_ids = {
        "device": "",
        "project": str(project_id) if project_id else None,
        "workspace": str(workspace_id) if workspace_id else None,
    }
    for scope_type in _SCOPE_PRECEDENCE:
        scope_id = scope_ids[scope_type]
        if scope_id is None:
            continue
        for phase_id, is_on in get_scope_settings(db, scope_type, scope_id).items():
            if phase_id not in universe:
                continue
            if is_on:
                enabled.add(phase_id)
            else:
                enabled.discard(phase_id)


def _load_workspace_row(db, workspace_id):
    if workspace_id is None:
        return None
    return db.execute(
        "SELECT id, project_id, work_mode_id FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()


def _load_mode_phase_rows(db, mode_id):
    return db.execute(
        "SELECT phase_id, enabled, position FROM work_mode_phases "
        "WHERE work_mode_id = ? ORDER BY position, phase_id",
        (mode_id,),
    ).fetchall()


def _basic_mode_id(db) -> int | None:
    row = db.execute(
        "SELECT id FROM work_modes WHERE name = 'basic'"
    ).fetchone()
    return row["id"] if row is not None else None


def _apply_work_mode_baseline(db, workspace_id, enabled: set, universe: set) -> None:
    """Disable phases that the workspace's work mode pins as ``enabled=0``.

    Phases not listed in the mode are left unchanged (i.e. inherit the caller's
    default-enabled assumption). Phases listed with ``enabled=1`` are forced
    on so a stale scope-override row from before mode reassignment cannot
    silently keep them off. When the workspace is missing entirely, the mode
    layer is a no-op so callers exercising the legacy ``resolve_enabled_phases``
    API with a synthetic ``workspace_id`` aren't penalised. When the workspace
    exists but has no ``work_mode_id``, the seeded ``basic`` mode is used so
    the canonical sequence still pins through.
    """
    ws_row = _load_workspace_row(db, workspace_id)
    if ws_row is None:
        return
    mode_id = ws_row["work_mode_id"]
    if mode_id is None:
        mode_id = _basic_mode_id(db)
        if mode_id is None:
            return

    for row in _load_mode_phase_rows(db, mode_id):
        phase_id = row["phase_id"]
        if phase_id not in universe:
            continue
        if row["enabled"]:
            enabled.add(phase_id)
        else:
            enabled.discard(phase_id)


def resolve_enabled_phases(db, workspace_id, project_id, all_phase_ids: set) -> set:
    """Return the enabled subset of ``all_phase_ids`` for the given scopes.

    Layers, in increasing precedence:
        - default (every id in ``all_phase_ids`` enabled)
        - workspace's work-mode baseline (only flips ids the mode lists)
        - device → project → workspace ``phase_settings`` overrides

    Additions are constrained to ``all_phase_ids`` so callers never see phase
    ids outside their declared universe. ``workspace_id`` may be ``None`` for
    callers that only care about device/project layering.
    """
    universe = set(all_phase_ids)
    enabled = set(universe)
    _apply_work_mode_baseline(db, workspace_id, enabled, universe)
    _apply_scope_overrides(db, workspace_id, project_id, enabled, universe)
    return enabled


def resolve_for_workspace(db, workspace_id) -> list[str]:
    """Return the ordered list of effective enabled phases for a workspace.

    Resolution order:
        1. Baseline = ``work_mode_phases`` for the workspace's assigned mode.
           Phase ids are kept in their stored ``position`` order so an
           operator can reorder a custom mode's sequence without changing
           code.
        2. Apply per-scope overrides (device → project → workspace) on top,
           same precedence as the legacy resolver.
        3. Filter to phases that resolved as enabled, preserving the
           baseline order.

    Returns ``[]`` when the workspace is unknown. When the workspace exists
    but has no ``work_mode_id`` (shouldn't happen after migration 0030, but
    can happen for legacy fixtures), falls back to the seeded ``basic``
    mode so the resolver still produces a meaningful sequence. Plan-expanded
    execution phases are not included here; composing them with the plan is
    the sequencer's responsibility (see ``services.phase_sequencer``).

    Changing a workspace.work_mode_id mid-task re-evaluates the phase
    sequence on the next call but does NOT mutate workspaces.phase. The
    agent stays on its current phase column value until normal advancement.
    """
    ws_row = _load_workspace_row(db, workspace_id)
    if ws_row is None:
        return []

    mode_id = ws_row["work_mode_id"]
    if mode_id is None:
        mode_id = _basic_mode_id(db)
        if mode_id is None:
            return []

    mode_phase_rows = _load_mode_phase_rows(db, mode_id)
    ordered_phase_ids = [row["phase_id"] for row in mode_phase_rows]
    baseline_enabled = {
        row["phase_id"] for row in mode_phase_rows if row["enabled"]
    }

    universe = set(ordered_phase_ids)
    enabled = set(baseline_enabled)
    _apply_scope_overrides(db, workspace_id, ws_row["project_id"], enabled, universe)

    return [pid for pid in ordered_phase_ids if pid in enabled]
