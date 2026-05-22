"""Resolve effective enabled-phase set across work mode + scope overrides.

Order of precedence (lowest to highest):
    1. ``work_mode_phases`` rows for the workspace's assigned mode supply the
       baseline. Phases listed with ``enabled=0`` are disabled; phases listed
       with ``enabled=1`` are enabled. Phases NOT listed in the mode default
       to enabled, so plan-expanded ``3.N.K`` execution phases still appear
       even though only canonical (non-templated) ids are seeded into modes.
    2. ``phase_settings`` rows at scope ``device``, then ``project``, then
       ``workspace`` may flip individual ids on or off.

Templated execution phases (``3.x.K``) are first-class targets in
``work_mode_phases``: a row pinned at ``3.x.0`` flips the implementation slot
for every ``3.N.0`` in the resolved sequence. Concrete ``3.N.K`` ids inherit
the templated parent's enabled flag at lookup time via ``templated_form``.

Scope overrides may also target concrete ``3.N.K`` ids directly. Their universe
is widened so a workspace-level ``3.5.3=False`` row is honored in
``resolve_for_workspace`` even though only the templated form lives in the
mode rows.
"""
import logging

from core.phase import is_templated, templated_form
from services.phase_settings import get_scope_settings

_SCOPE_PRECEDENCE = ("device", "project", "workspace")
_LOG = logging.getLogger(__name__)


def _index_mode_phases(mode_phase_rows) -> dict[str, bool]:
    """Build a ``phase_id -> enabled bool`` index from the raw mode rows.

    The orchestrator path calls into this index repeatedly so the conversion
    happens once and the result is reused across baseline + scope-override
    application.
    """
    return {row["phase_id"]: bool(row["enabled"]) for row in mode_phase_rows}


def _resolve_mode_enabled(phase_id: str, mode_phases: dict[str, bool]) -> bool | None:
    """Look up the mode's enabled flag for a phase id.

    Returns the concrete row's flag when present; otherwise falls back to the
    templated parent (``3.N.K -> 3.x.K``) so concrete execution sub-phases
    inherit their family's enable/disable. Returns ``None`` when neither key
    is present, signalling that the universe-default should apply.
    """
    if phase_id in mode_phases:
        return mode_phases[phase_id]
    parent = templated_form(phase_id)
    if parent is not None and parent in mode_phases:
        return mode_phases[parent]
    return None


def _is_known_phase_id(phase_id: str) -> bool:
    """Return True when the phase id maps to a registered phase or template."""
    from advance.phases import PHASE_REGISTRY

    if phase_id in PHASE_REGISTRY:
        return True
    parent = templated_form(phase_id)
    return parent is not None and parent in PHASE_REGISTRY


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


def _resolve_effective_mode_id(db, workspace_id) -> int | None:
    """Return the mode the workspace's resolution should run against.

    Workspaces with no ``work_mode_id`` fall back to the seeded ``basic`` mode
    so legacy fixtures and freshly-created rows still produce meaningful
    phase sequences.
    """
    ws_row = _load_workspace_row(db, workspace_id)
    if ws_row is None:
        return None
    mode_id = ws_row["work_mode_id"]
    if mode_id is None:
        return _basic_mode_id(db)
    return mode_id


def _apply_work_mode_baseline(db, workspace_id, enabled: set, universe: set) -> None:
    """Disable / enable phases according to the workspace's assigned mode.

    A row whose ``phase_id`` references neither a concrete registered phase
    nor a templated parent in the registry is logged at ``warning`` level and
    skipped — observable but never raises. For every other row the helper
    iterates the universe and uses ``_resolve_mode_enabled`` so concrete
    ``3.N.K`` ids inherit their templated parent's flag.

    When the workspace is missing entirely, the mode layer is a no-op so
    callers exercising the legacy ``resolve_enabled_phases`` API with a
    synthetic ``workspace_id`` aren't penalised.
    """
    mode_id = _resolve_effective_mode_id(db, workspace_id)
    if mode_id is None:
        return

    mode_phase_rows = _load_mode_phase_rows(db, mode_id)
    mode_phases = _index_mode_phases(mode_phase_rows)
    _warn_about_unknown_mode_rows(mode_phases.keys())

    for phase_id in universe:
        flag = _resolve_mode_enabled(phase_id, mode_phases)
        if flag is True:
            enabled.add(phase_id)
        elif flag is False:
            enabled.discard(phase_id)


def _warn_about_unknown_mode_rows(phase_ids) -> None:
    """Emit a single warning per unrecognised phase id."""
    for phase_id in phase_ids:
        if not _is_known_phase_id(phase_id):
            _LOG.warning(
                "work_mode_phase row references unknown phase id: %r", phase_id
            )


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


def _scope_override_phase_ids(db, workspace_id, project_id) -> set[str]:
    """Collect every phase id touched by any applicable scope-override row."""
    scope_ids = {
        "device": "",
        "project": str(project_id) if project_id else None,
        "workspace": str(workspace_id) if workspace_id else None,
    }
    collected: set[str] = set()
    for scope_type, scope_id in scope_ids.items():
        if scope_id is None:
            continue
        collected.update(get_scope_settings(db, scope_type, scope_id).keys())
    return collected


def resolve_for_workspace(db, workspace_id) -> list[str]:
    """Return the ordered list of effective enabled phases for a workspace.

    Resolution order:
        1. Baseline = ``work_mode_phases`` for the workspace's assigned mode.
           Phase ids are kept in their stored ``position`` order so an
           operator can reorder a custom mode's sequence without changing
           code.
        2. The universe is extended with concrete ``3.N.K`` scope-override
           targets whose templated parent is registered, so a workspace can
           toggle a specific execution sub-phase without the mode storing
           every concrete expansion.
        3. Apply per-scope overrides (device → project → workspace) on top,
           same precedence as the legacy resolver.
        4. Filter to phases that resolved as enabled, preserving the
           baseline order; ids introduced by scope overrides keep
           ``phase_key`` ordering relative to the baseline.

    Returns ``[]`` when the workspace is unknown. When the workspace exists
    but has no ``work_mode_id`` (shouldn't happen after migration 0030, but
    can happen for legacy fixtures), falls back to the seeded ``basic``
    mode so the resolver still produces a meaningful sequence.

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
    mode_phases = _index_mode_phases(mode_phase_rows)
    _warn_about_unknown_mode_rows(mode_phases.keys())

    ordered_phase_ids = [row["phase_id"] for row in mode_phase_rows]
    universe = set(ordered_phase_ids)

    extra_ordered = _extend_universe_from_scope_overrides(
        db, workspace_id, ws_row["project_id"], universe
    )

    enabled = {
        phase_id
        for phase_id in universe
        if _resolve_mode_enabled(phase_id, mode_phases) is not False
    }
    _apply_scope_overrides(db, workspace_id, ws_row["project_id"], enabled, universe)

    return [pid for pid in ordered_phase_ids + extra_ordered if pid in enabled]


def resolve_for_project(db, project_id: int) -> list[str]:
    """Return the ordered list of effective enabled phases for a project.

    Projects have no ``work_mode_id`` of their own; the ``basic`` mode
    supplies the baseline. Device- and project-level scope overrides are
    applied; workspace-level overrides are excluded because no workspace
    is in scope when writing project-level config files.

    Returns ``[]`` when the basic mode is not seeded.
    """
    mode_id = _basic_mode_id(db)
    if mode_id is None:
        return []

    mode_phase_rows = _load_mode_phase_rows(db, mode_id)
    mode_phases = _index_mode_phases(mode_phase_rows)
    _warn_about_unknown_mode_rows(mode_phases.keys())

    ordered_phase_ids = [row["phase_id"] for row in mode_phase_rows]
    universe = set(ordered_phase_ids)

    enabled = {
        phase_id
        for phase_id in universe
        if _resolve_mode_enabled(phase_id, mode_phases) is not False
    }
    _apply_scope_overrides(db, None, project_id, enabled, universe)

    return [pid for pid in ordered_phase_ids if pid in enabled]


def _extend_universe_from_scope_overrides(
    db, workspace_id, project_id, universe: set
) -> list[str]:
    """Pull templated-family scope-override targets into the universe.

    Scope overrides addressing concrete ``3.N.K`` ids (whose templated parent
    is registered) are added so they can be honored even though the mode rows
    store only the templated form. Returns the newly introduced ids in
    ``phase_key`` order so the final sequence stays sorted within the
    appended tail.
    """
    from core.phase import phase_key

    candidates = _scope_override_phase_ids(db, workspace_id, project_id)
    extras: set[str] = set()
    for phase_id in candidates:
        if phase_id in universe:
            continue
        if is_templated(phase_id):
            continue
        if _is_known_phase_id(phase_id):
            extras.add(phase_id)
    universe.update(extras)
    return sorted(extras, key=phase_key)
