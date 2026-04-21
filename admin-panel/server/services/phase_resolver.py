"""Resolve effective enabled-phase set across device/project/workspace scopes."""
from services.phase_settings import get_scope_settings, is_always_on

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


def _enforce_always_on(enabled: set, universe: set) -> None:
    """Force always-on phase ids to stay enabled. Mutates ``enabled`` in place."""
    for phase_id in universe:
        if is_always_on(phase_id):
            enabled.add(phase_id)


def resolve_enabled_phases(db, workspace_id, project_id, all_phase_ids: set) -> set:
    """Return the enabled subset of ``all_phase_ids`` for the given scopes.

    Scope precedence: device < project < workspace. Each layer may enable or
    disable phases. Additions are constrained to ``all_phase_ids`` so callers
    never see phase ids outside their declared universe. Always-on phases are
    forced last so no layer can accidentally drop them.
    """
    universe = set(all_phase_ids)
    enabled = set(universe)
    _apply_scope_overrides(db, workspace_id, project_id, enabled, universe)
    _enforce_always_on(enabled, universe)
    return enabled
