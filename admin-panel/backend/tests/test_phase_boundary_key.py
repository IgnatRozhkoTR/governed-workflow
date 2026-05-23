"""Tests for Phase.boundary_key across all phase families."""
import pytest

from advance.phases import get_phase, PHASE_REGISTRY
from advance.phases.execution import get_execution_phase


# ── Preparation phases ────────────────────────────────────────────────────────


@pytest.mark.parametrize("phase_id", ["0", "1.0", "1.1", "1.2", "1.3", "1.4"])
def test_preparation_phases_boundary_key_is_first_segment(phase_id):
    phase = get_phase(phase_id)
    assert phase is not None, f"Phase {phase_id!r} is not registered"

    assert phase.boundary_key == phase_id.split(".")[0]


# ── Planning phases ───────────────────────────────────────────────────────────


def test_planning_phase_2_0_boundary_key_is_2():
    phase = get_phase("2.0")
    assert phase is not None

    assert phase.boundary_key == "2"


def test_planning_phase_2_1_boundary_key_when_registered():
    phase = get_phase("2.1")
    if phase is None:
        pytest.skip("Phase 2.1 is a module-contributed DeclarativePhase not registered in this environment")

    assert phase.boundary_key == "2"


# ── Execution phases ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("n,k", [
    (1, 0),
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
])
def test_execution_sub_phases_for_n1_boundary_key_is_3_1(n, k):
    phase = get_execution_phase(n, k)
    assert phase is not None

    assert phase.boundary_key == f"3.{n}"


@pytest.mark.parametrize("n,k", [
    (5, 0),
    (5, 4),
])
def test_execution_sub_phases_for_n5_boundary_key_is_3_5(n, k):
    phase = get_execution_phase(n, k)
    assert phase is not None

    assert phase.boundary_key == f"3.{n}"


@pytest.mark.parametrize("phase_id,expected_boundary", [
    ("3.1.0", "3.1"),
    ("3.1.2", "3.1"),
    ("3.5.4", "3.5"),
])
def test_execution_phase_boundary_key_via_get_phase(phase_id, expected_boundary):
    phase = get_phase(phase_id)
    assert phase is not None, f"get_phase({phase_id!r}) returned None"

    assert phase.boundary_key == expected_boundary


def test_execution_template_phases_boundary_key_is_3_x():
    template_ids = [f"3.x.{k}" for k in range(5)]
    for phase_id in template_ids:
        phase = get_phase(phase_id)
        assert phase is not None, f"Template phase {phase_id!r} is not in PHASE_REGISTRY"
        assert phase.boundary_key == "3.x", (
            f"Expected boundary_key='3.x' for {phase_id!r}, got {phase.boundary_key!r}"
        )


# ── Finalization phases ───────────────────────────────────────────────────────


@pytest.mark.parametrize("phase_id", ["4.0", "4.1", "4.2"])
def test_finalization_phases_boundary_key_is_4(phase_id):
    phase = get_phase(phase_id)
    assert phase is not None

    assert phase.boundary_key == "4"


# ── Done phase ────────────────────────────────────────────────────────────────


def test_done_phase_boundary_key_is_5():
    phase = get_phase("5")
    assert phase is not None

    assert phase.boundary_key == "5"
