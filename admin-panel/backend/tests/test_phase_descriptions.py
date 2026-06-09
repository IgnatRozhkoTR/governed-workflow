"""Tests for Phase.description_for_skill() across every registered phase.

Sub-phase 3.1: every Phase must contribute either an empty string (signalling
"omit me from the rendered SKILL.md") or a non-empty markdown block beginning
with a top-level heading. The base class returns "" so unconfigured
subclasses default to omission. The execution template family must yield
distinct content per slot so the rendered skill carries five separately
addressable steps.
"""

import pytest

from advance.permissions import get_phase_permissions
from advance.phases import PHASE_REGISTRY, Phase
from advance.phases.declarative import DeclarativePhase
from advance.phases.execution import _ExecutionTemplatePhase


def test_base_phase_description_returns_empty_string():
    """A Phase subclass that does not override description_for_skill returns ''."""

    class _MinimalPhase(Phase):
        id = "test.base"
        name = "Minimal Test Phase"

        def validate(self, ws, body, project_path):
            return True, {}

        def next_phase(self, ws):
            return self.id

    assert _MinimalPhase().description_for_skill() == ""


@pytest.mark.parametrize("phase_id", sorted(PHASE_REGISTRY.keys()))
def test_registered_phase_description_is_empty_or_markdown_heading(phase_id):
    """Every registered phase contributes either '' or markdown starting with '## '.

    DeclarativePhases with no manifest entry yield ''. All hand-written phases
    contribute a top-level (##) section so the rendered SKILL.md has a clean
    outline.
    """
    phase = PHASE_REGISTRY[phase_id]
    block = phase.description_for_skill()
    assert isinstance(block, str)
    if block == "":
        return
    stripped = block.lstrip()
    assert stripped.startswith("## "), (
        f"Phase {phase_id!r} description must start with '## ' or be empty; "
        f"got prefix: {stripped[:40]!r}"
    )


def test_declarative_phase_with_no_description_returns_empty():
    """DeclarativePhase built from a minimal manifest defaults description to ''."""
    phase = DeclarativePhase({"id": "9.9", "name": "Test"})
    assert phase.description_for_skill() == ""


def test_declarative_phase_carries_manifest_description():
    """DeclarativePhase exposes the manifest's description_for_skill verbatim."""
    phase = DeclarativePhase({
        "id": "9.9",
        "name": "Test",
        "description_for_skill": "## 9.9 Custom\n\nBody.",
    })
    assert phase.description_for_skill() == "## 9.9 Custom\n\nBody."


@pytest.mark.parametrize("k", [0, 1, 2, 3, 4])
def test_execution_template_phase_description_non_empty_and_heading(k):
    """Every 3.x.K template carries its own description starting with '## '."""
    phase = _ExecutionTemplatePhase(k)
    block = phase.description_for_skill()
    assert block, f"_ExecutionTemplatePhase({k}) returned empty description"
    assert block.lstrip().startswith("## ")


def test_execution_template_phase_descriptions_all_distinct():
    """The five template phases must each render unique markdown."""
    blocks = [_ExecutionTemplatePhase(k).description_for_skill() for k in range(5)]
    assert len(set(blocks)) == 5, "execution template descriptions are not unique"


def test_static_phase_count_have_descriptions():
    """Concrete (non-templated, non-declarative) phases all contribute markdown.

    Sanity check: the in-tree phase set in sub-phase 3.1 covers Init, all of
    1.x, 2.0, 4.0/4.1/4.2, 5. None of these may regress to empty.
    """
    expected_static_ids = {
        "0", "1.0", "1.1", "1.2", "1.3", "1.4",
        "2.0",
        "4.0", "4.1", "4.2", "5.1", "5.2", "6",
    }
    missing = []
    for phase_id in expected_static_ids:
        phase = PHASE_REGISTRY.get(phase_id)
        assert phase is not None, f"phase {phase_id!r} missing from PHASE_REGISTRY"
        if not phase.description_for_skill().strip():
            missing.append(phase_id)
    assert not missing, f"phases without description_for_skill: {missing}"


def test_static_phases_have_short_descriptions():
    """Every concrete phase rendered into the Phase Map must carry a short_description."""
    expected_static_ids = {
        "0", "1.0", "1.1", "1.2", "1.3", "1.4",
        "2.0",
        "4.0", "4.1", "4.2", "5.1", "5.2", "6",
    }
    missing = []
    for phase_id in expected_static_ids:
        phase = PHASE_REGISTRY.get(phase_id)
        assert phase is not None
        if not phase.short_description.strip():
            missing.append(phase_id)
    assert not missing, f"phases without short_description: {missing}"


@pytest.mark.parametrize("k", [0, 1, 2, 3, 4])
def test_execution_template_phase_short_description_non_empty(k):
    """Every 3.x.K template carries a short_description for the Phase Map render."""
    phase = _ExecutionTemplatePhase(k)
    assert phase.short_description.strip(), (
        f"_ExecutionTemplatePhase({k}) returned empty short_description"
    )


def test_base_phase_short_description_returns_empty_string():
    """A Phase subclass that does not override short_description returns ''."""

    class _MinimalPhase(Phase):
        id = "test.short"
        name = "Minimal Short"

        def validate(self, ws, body, project_path):
            return True, {}

        def next_phase(self, ws):
            return self.id

    assert _MinimalPhase().short_description == ""


def test_declarative_phase_carries_manifest_short_description():
    """DeclarativePhase exposes the manifest's short_description verbatim."""
    phase = DeclarativePhase({
        "id": "9.9",
        "name": "Test",
        "short_description": "One-line summary",
    })
    assert phase.short_description == "One-line summary"


@pytest.mark.parametrize(
    "phase_id, expected",
    [
        ("0", (False, False, False)),
        ("1.0", (False, False, False)),
        ("1.4", (False, False, False)),
        ("2.0", (False, False, False)),
        ("3.1.0", (True, False, False)),
        ("3.1.1", (False, False, False)),
        ("3.1.2", (True, False, False)),
        ("3.1.3", (False, False, False)),
        ("3.1.4", (False, True, False)),
        ("3.x.0", (True, False, False)),
        ("3.x.4", (False, True, False)),
        ("4.0", (False, False, False)),
        ("4.1", (True, True, False)),
        ("4.2", (False, False, False)),
        ("6", (False, False, True)),
    ],
)
def test_get_phase_permissions_matches_runtime_policy(phase_id, expected):
    """get_phase_permissions mirrors the regex-driven policy used at advance-time."""
    assert get_phase_permissions(phase_id) == expected
