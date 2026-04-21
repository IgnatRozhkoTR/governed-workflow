"""Compose the effective phase sequence for a workspace.

Centralizes the three concerns that used to be scattered across routes,
mcp_tools and the orchestrator:

- Read module-contributed DeclarativePhases from ``advance.phases``.
- Splice them into the static phase sequence via ``compute_phase_sequence``.
- Resolve the enabled subset from per-level phase settings.

This module depends on ``advance.phases``; ``core.helpers`` does not, so the
leaf-ness of ``core`` is preserved.
"""
import json

from advance.phases import PHASE_REGISTRY
from advance.phases.declarative import DeclarativePhase
from core.helpers import compute_phase_sequence
from services.phase_resolver import resolve_enabled_phases


def module_phases_by_band() -> tuple[list[str], list[str]]:
    """Return (preparation_ids, finalization_ids) for module-contributed phases.

    Each list is sorted by declared position. Phases registered with bands
    other than ``preparation`` or ``finalization`` are filtered out upstream
    by the module loader.
    """
    prep = sorted(
        (p for p in PHASE_REGISTRY.values()
         if isinstance(p, DeclarativePhase) and p.band == "preparation"),
        key=lambda p: p.position,
    )
    final = sorted(
        (p for p in PHASE_REGISTRY.values()
         if isinstance(p, DeclarativePhase) and p.band == "finalization"),
        key=lambda p: p.position,
    )
    return [p.id for p in prep], [p.id for p in final]


def full_phase_sequence(plan) -> list[str]:
    """Build the complete phase sequence including module-contributed phases."""
    return compute_phase_sequence(plan, module_phases_by_band=module_phases_by_band())


def resolve_phase_sequence(db, ws, plan) -> tuple[set[str], list[str]]:
    """Resolve the enabled set and the filtered phase sequence for a workspace.

    Returns ``(enabled_phase_ids, sequence_of_enabled_ids_in_order)``.
    """
    full = full_phase_sequence(plan)
    enabled = resolve_enabled_phases(db, ws["id"], ws["project_id"], set(full))
    sequence = [p for p in full if p in enabled]
    return enabled, sequence


def plan_from_workspace(ws) -> dict:
    """Decode the plan JSON from a workspace row. Empty dict when absent."""
    plan_json = ws["plan_json"] if "plan_json" in ws.keys() else None
    if not plan_json:
        return {}
    try:
        return json.loads(plan_json)
    except (json.JSONDecodeError, TypeError):
        return {}
