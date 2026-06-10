"""Resolve effective enabled-phase set for workspace / project scope.

Order of precedence (lowest to highest):
    1. Baseline: every registered phase is enabled by default. The universe
       of phase ids comes from the caller (``resolve_enabled_phases``) or
       from ``PHASE_REGISTRY`` (``resolve_for_project`` /
       ``resolve_for_workspace``).
    2. ``phase_settings`` rows at scope ``device``, then ``project``, then
       ``workspace`` flip individual ids on or off. Workspace overrides win
       over project, project over device.

Concrete execution ids (``3.N.K``) inherit the templated parent's flag from
the scope-override layer via ``templated_form``: a row that targets
``3.x.0`` flips every ``3.N.0`` in the universe. Scope overrides may also
target concrete ``3.N.K`` ids directly; the workspace resolver widens the
universe so those targets are honored.
"""
from core.phase import is_templated, phase_key, templated_form
from services.phase_settings import get_scope_settings

_SCOPE_PRECEDENCE = ("device", "project", "workspace")


def _resolve_override_flag(phase_id: str, overrides: dict[str, bool]) -> bool | None:
    """Look up the override flag for a phase id, inheriting from its templated parent.

    Returns the concrete row's flag when present; otherwise falls back to the
    templated parent (``3.N.K -> 3.x.K``) so concrete execution sub-phases
    inherit their family's enable/disable from scope overrides. Returns
    ``None`` when neither key is present.
    """
    if phase_id in overrides:
        return overrides[phase_id]
    parent = templated_form(phase_id)
    if parent is not None and parent in overrides:
        return overrides[parent]
    return None


def _is_known_phase_id(phase_id: str) -> bool:
    """Return True when the phase id maps to a registered phase or template."""
    from advance.phases import PHASE_REGISTRY

    if phase_id in PHASE_REGISTRY:
        return True
    parent = templated_form(phase_id)
    return parent is not None and parent in PHASE_REGISTRY


def _collect_overrides(db, workspace_id, project_id, scopes: tuple[str, ...]) -> dict[str, bool]:
    """Merge per-level phase-settings rows in precedence order.

    Later scopes overwrite earlier ones, so the returned mapping yields the
    effective flag per phase id for the requested resolution.
    """
    scope_ids = {
        "device": "",
        "project": str(project_id) if project_id else None,
        "workspace": str(workspace_id) if workspace_id else None,
    }
    overrides: dict[str, bool] = {}
    for scope_type in scopes:
        scope_id = scope_ids.get(scope_type)
        if scope_id is None:
            continue
        overrides.update(get_scope_settings(db, scope_type, scope_id))
    return overrides


def _load_workspace_row(db, workspace_id):
    if workspace_id is None:
        return None
    return db.execute(
        "SELECT id, project_id FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()


def _canonical_registered_ids(include_templated: bool = False) -> list[str]:
    """Registered phase ids, sorted in canonical order.

    Templated execution ids (``3.x.K``) are excluded by default. When
    ``include_templated`` is True they are kept and sorted inline; ``phase_key``
    places ``3.x.K`` between ``2.x`` and ``4.0`` so the execution family renders
    in its natural workflow position.
    """
    from advance.phases import PHASE_REGISTRY

    return sorted(
        (
            pid
            for pid in PHASE_REGISTRY.keys()
            if include_templated or not is_templated(pid)
        ),
        key=phase_key,
    )


def _apply_scope_overrides(enabled: set, overrides: dict[str, bool], universe: set) -> None:
    """Flip ids in ``enabled`` according to overrides, constrained to ``universe``."""
    for phase_id in universe:
        flag = _resolve_override_flag(phase_id, overrides)
        if flag is True:
            enabled.add(phase_id)
        elif flag is False:
            enabled.discard(phase_id)


def _widen_universe_with_overrides(
    overrides: dict[str, bool], universe: set
) -> list[str]:
    """Add concrete override targets to the universe, returning the new ids in order.

    Scope overrides addressing concrete ``3.N.K`` ids whose templated parent is
    registered are added so they can be honored even though they are not part
    of the baseline universe. Templated ids (``3.x.K``) themselves are not
    added because they only act as parents.
    """
    extras: set[str] = set()
    for phase_id in overrides.keys():
        if phase_id in universe:
            continue
        if is_templated(phase_id):
            continue
        if _is_known_phase_id(phase_id):
            extras.add(phase_id)
    universe.update(extras)
    return sorted(extras, key=phase_key)


def resolve_enabled_phases(db, workspace_id, project_id, all_phase_ids: set) -> set:
    """Return the enabled subset of ``all_phase_ids`` for the given scopes.

    Layers, in increasing precedence:
        - default (every id in ``all_phase_ids`` enabled)
        - device → project → workspace ``phase_settings`` overrides

    Additions are constrained to ``all_phase_ids`` so callers never see phase
    ids outside their declared universe. ``workspace_id`` may be ``None`` for
    callers that only care about device/project layering.
    """
    universe = set(all_phase_ids)
    enabled = set(universe)
    overrides = _collect_overrides(db, workspace_id, project_id, _SCOPE_PRECEDENCE)
    _apply_scope_overrides(enabled, overrides, universe)
    return enabled


def resolve_for_workspace(db, workspace_id) -> list[str]:
    """Return the ordered list of effective enabled phases for a workspace.

    Resolution order:
        1. Baseline = every canonical registered phase id, in ``phase_key``
           order. Templated ids (``3.x.K``) are excluded — they describe a
           per-plan family, not a standalone enable/disable target.
        2. The universe is widened with concrete ``3.N.K`` scope-override
           targets whose templated parent is registered, so a workspace can
           toggle a specific execution sub-phase.
        3. Device → project → workspace scope overrides flip ids on or off.
        4. Filter to phases that resolved as enabled, preserving canonical
           order; ids introduced by scope overrides are appended in
           ``phase_key`` order.

    Returns ``[]`` when the workspace is unknown.
    """
    ws_row = _load_workspace_row(db, workspace_id)
    if ws_row is None:
        return []

    ordered_phase_ids = _canonical_registered_ids()
    universe = set(ordered_phase_ids)

    overrides = _collect_overrides(db, workspace_id, ws_row["project_id"], _SCOPE_PRECEDENCE)
    extra_ordered = _widen_universe_with_overrides(overrides, universe)

    enabled = set(universe)
    _apply_scope_overrides(enabled, overrides, universe)

    return [pid for pid in ordered_phase_ids + extra_ordered if pid in enabled]


def resolve_for_project(db, project_id, include_templated: bool = False) -> list[str]:
    """Return the ordered list of effective enabled phases for a project.

    Baseline is every canonical registered phase id. Device- and project-level
    scope overrides are applied; workspace-level overrides are excluded
    because no workspace is in scope when writing project-level config files.

    With ``include_templated`` the templated execution ids (``3.x.0..3.x.4``)
    are kept in the result, sorted into their natural position between ``2.x``
    and ``4.0``. Scope overrides addressing those literal templated ids still
    apply. Defaults to False so callers that render one entry per concrete
    phase are unaffected.
    """
    ordered_phase_ids = _canonical_registered_ids(include_templated)
    universe = set(ordered_phase_ids)

    overrides = _collect_overrides(db, None, project_id, ("device", "project"))

    enabled = set(universe)
    _apply_scope_overrides(enabled, overrides, universe)

    return [pid for pid in ordered_phase_ids if pid in enabled]
