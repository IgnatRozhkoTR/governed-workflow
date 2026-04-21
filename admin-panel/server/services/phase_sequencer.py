"""Compose the effective phase sequence for a workspace.

The sequencer is the integration point between the leaf-level
``compute_phase_sequence`` and the advance-layer ``PHASE_REGISTRY``. It hands
the registry's keys to core so the sequence is ordered consistently with
``phase_key``, including any module-contributed phases and the expanded
execution templates derived from the plan.
"""
import json

from advance.phases import PHASE_REGISTRY
from core.helpers import compute_phase_sequence
from services.phase_resolver import resolve_enabled_phases


def _registered_phase_ids() -> list[str]:
    """Snapshot the current PHASE_REGISTRY ids for the sequencer."""
    return list(PHASE_REGISTRY.keys())


def full_phase_sequence(plan) -> list[str]:
    """Build the complete phase sequence for the plan, templates expanded."""
    return compute_phase_sequence(plan, registered_phase_ids=_registered_phase_ids())


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
