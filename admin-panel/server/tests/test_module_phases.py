"""Tests for module-contributed phases (phase 3.5)."""
import pytest

from advance.phases import PHASE_REGISTRY, register_phase
from advance.phases.declarative import DeclarativePhase
from core.helpers import compute_phase_sequence
from services.module_phase_loader import load_module_phases


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
    assert p3.next_phase({}) == ""


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
        "id: mod.check\nname: Mod Check\nband: preparation\nposition: 500\n"
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
        "id: mod.v\nname: V\nband: preparation\nposition: 500\nvalidator: my_validator\n"
    )
    (mod / "phase_factory.py").write_text(
        "def my_validator(ws, body, pp):\n    return (False, {'test': 1})\n"
    )
    result = load_module_phases([mod])
    assert len(result) == 1
    assert result[0].validate({}, {}, "") == (False, {"test": 1})


def test_load_module_phases_skips_unsupported_band(tmp_path):
    pytest.importorskip("yaml")
    mod = tmp_path / "mod3"
    mod.mkdir()
    (mod / "phase.yaml").write_text(
        "id: mod.plan\nname: P\nband: planning\nposition: 500\n"
    )
    assert load_module_phases([mod]) == []


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
    phase = DeclarativePhase(
        {"id": "mod.prep.x", "name": "Mod Prep", "band": "preparation", "position": 500}
    )
    register_phase(phase)
    yield phase
    PHASE_REGISTRY.pop("mod.prep.x", None)


@pytest.fixture
def registered_final_phase():
    phase = DeclarativePhase(
        {"id": "mod.final.x", "name": "Mod Final", "band": "finalization", "position": 500}
    )
    register_phase(phase)
    yield phase
    PHASE_REGISTRY.pop("mod.final.x", None)


@pytest.fixture
def two_prep_phases():
    p_early = DeclarativePhase(
        {"id": "mod.prep.early", "name": "Early", "band": "preparation", "position": 200}
    )
    p_late = DeclarativePhase(
        {"id": "mod.prep.late", "name": "Late", "band": "preparation", "position": 800}
    )
    register_phase(p_early)
    register_phase(p_late)
    yield p_early, p_late
    PHASE_REGISTRY.pop("mod.prep.early", None)
    PHASE_REGISTRY.pop("mod.prep.late", None)


def test_compute_phase_sequence_includes_module_prep_phase(registered_prep_phase):
    seq = compute_phase_sequence({})
    assert "mod.prep.x" in seq
    idx = seq.index("mod.prep.x")
    assert seq.index("2.1") < idx < seq.index("4.0")


def test_compute_phase_sequence_includes_module_finalization_phase(registered_final_phase):
    seq = compute_phase_sequence({})
    assert "mod.final.x" in seq
    idx = seq.index("mod.final.x")
    assert seq.index("2.1") < idx < seq.index("4.0")


def test_compute_phase_sequence_respects_position_within_band(two_prep_phases):
    seq = compute_phase_sequence({})
    assert seq.index("mod.prep.early") < seq.index("mod.prep.late")
