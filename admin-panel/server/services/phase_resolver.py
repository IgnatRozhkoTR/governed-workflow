"""Resolve effective enabled-phase set across device/project/workspace scopes."""
from services.phase_settings import get_scope_settings, is_always_on


def resolve_enabled_phases(db, workspace_id, project_id, all_phase_ids: set) -> set:
    enabled = set(all_phase_ids)

    for scope_type, scope_id in (
        ("device", ""),
        ("project", str(project_id) if project_id else None),
        ("workspace", str(workspace_id) if workspace_id else None),
    ):
        if scope_id is None:
            continue
        for phase_id, is_on in get_scope_settings(db, scope_type, scope_id).items():
            if is_on:
                enabled.add(phase_id)
            else:
                enabled.discard(phase_id)

    for phase_id in all_phase_ids:
        if is_always_on(phase_id):
            enabled.add(phase_id)

    return enabled
