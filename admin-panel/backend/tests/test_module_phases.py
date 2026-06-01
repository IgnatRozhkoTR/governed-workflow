"""Tests for module-contributed phases (phase 3.5)."""
import pytest

from advance.phases import PHASE_REGISTRY, register_phase
from advance.phases.declarative import DeclarativePhase
from services.module_phase_loader import load_module_phases
from services.phase_sequencer import full_phase_sequence


# ── DeclarativePhase ─────────────────────────────────────────────────────────


def test_declarative_phase_basic_properties():
    manifest = {"id": "p.min", "name": "Minimal Phase"}
    phase = DeclarativePhase(manifest)
    assert phase.id == "p.min"
    assert phase.name == "Minimal Phase"
    assert phase.is_user_gate is False


def test_declarative_phase_user_gate_properties():
    manifest = {
        "id": "p.gate", "name": "Gate",
        "is_user_gate": True, "approve_target": "2.0", "reject_target": "1.1",
    }
    phase = DeclarativePhase(manifest)
    assert phase.is_user_gate is True
    assert phase.approve_target == "2.0"
    assert phase.reject_target == "1.1"


def test_declarative_phase_validate_no_fn_returns_true():
    phase = DeclarativePhase({"id": "p.x", "name": "X"})
    assert phase.validate({}, {}, "") == (True, {})


def test_declarative_phase_validate_calls_validator_fn():
    fn = lambda ws, body, pp: (False, {"reason": "x"})
    phase = DeclarativePhase({"id": "p.x", "name": "X"}, validator_fn=fn)
    assert phase.validate({"id": 1}, {"k": "v"}, "/tmp") == (False, {"reason": "x"})


def test_declarative_phase_next_phase_returns_approve_target_first():
    p1 = DeclarativePhase({"id": "a", "name": "A", "approve_target": "2.0", "reject_target": "1.1"})
    p2 = DeclarativePhase({"id": "b", "name": "B", "reject_target": "1.1"})
    p3 = DeclarativePhase({"id": "c", "name": "C"})
    assert p1.next_phase({}) == "2.0"
    assert p2.next_phase({}) == "1.1"
    assert p3.next_phase({}) == "c"


# ── load_module_phases ───────────────────────────────────────────────────────


def test_load_module_phases_empty_dirs_returns_empty():
    assert load_module_phases([]) == []


def test_load_module_phases_skips_dirs_without_manifest(tmp_path):
    (tmp_path / "empty_module").mkdir()
    assert load_module_phases([tmp_path / "empty_module"]) == []


def test_load_module_phases_parses_single_phase(tmp_path):
    pytest.importorskip("yaml")
    mod = tmp_path / "mod"
    mod.mkdir()
    (mod / "phase.yaml").write_text(
        "phases:\n  - id: mod.check\n    name: Mod Check\n"
    )
    result = load_module_phases([mod])
    assert len(result) == 1
    assert result[0].id == "mod.check"
    assert result[0].name == "Mod Check"


def test_load_module_phases_loads_validator_from_factory(tmp_path):
    pytest.importorskip("yaml")
    mod = tmp_path / "mod2"
    mod.mkdir()
    (mod / "phase.yaml").write_text(
        "phases:\n  - id: mod.v\n    name: V\n    validator: my_validator\n"
    )
    (mod / "phase_factory.py").write_text(
        "def my_validator(ws, body, pp):\n    return (False, {'test': 1})\n"
    )
    result = load_module_phases([mod])
    assert len(result) == 1
    assert result[0].validate({}, {}, "") == (False, {"test": 1})


def test_load_module_phases_handles_malformed_yaml(tmp_path):
    pytest.importorskip("yaml")
    mod = tmp_path / "mod4"
    mod.mkdir()
    (mod / "phase.yaml").write_text(":::\n\t- invalid: [yaml\n")
    result = load_module_phases([mod])
    assert result == []


# ── compute_phase_sequence with module phases ───────────────────────────────


@pytest.fixture
def registered_prep_phase():
    phase = DeclarativePhase({"id": "1.5", "name": "Mod Prep"})
    register_phase(phase)
    yield phase
    PHASE_REGISTRY.pop("1.5", None)


@pytest.fixture
def registered_final_phase():
    phase = DeclarativePhase({"id": "4.5", "name": "Mod Final"})
    register_phase(phase)
    yield phase
    PHASE_REGISTRY.pop("4.5", None)


@pytest.fixture
def two_prep_phases():
    p_early = DeclarativePhase({"id": "1.5", "name": "Early"})
    p_late = DeclarativePhase({"id": "1.6", "name": "Late"})
    register_phase(p_early)
    register_phase(p_late)
    yield p_early, p_late
    PHASE_REGISTRY.pop("1.5", None)
    PHASE_REGISTRY.pop("1.6", None)


def test_compute_phase_sequence_includes_module_prep_phase(registered_prep_phase):
    seq = full_phase_sequence({})
    assert "1.5" in seq
    idx = seq.index("1.5")
    assert seq.index("1.4") < idx < seq.index("2.0")


def test_compute_phase_sequence_includes_module_finalization_phase(registered_final_phase):
    seq = full_phase_sequence({})
    assert "4.5" in seq
    idx = seq.index("4.5")
    assert seq.index("4.2") < idx < seq.index("5.1")


def test_compute_phase_sequence_respects_phase_key_ordering(two_prep_phases):
    seq = full_phase_sequence({})
    assert seq.index("1.5") < seq.index("1.6")
