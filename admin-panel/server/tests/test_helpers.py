"""Tests for compute_phase_sequence filtering in helpers module."""
import pytest

from core.helpers import compute_phase_sequence, match_scope_pattern


# ── Existing match_scope_pattern tests ───────────────────────────────────────


def test_match_scope_pattern_returnsTrue_whenExactFileMatch():
    assert match_scope_pattern("src/main.py", "src/main.py") is True


def test_match_scope_pattern_returnsFalse_whenDifferentFile():
    assert match_scope_pattern("src/other.py", "src/main.py") is False


def test_match_scope_pattern_returnsTrue_whenStarMatchesSingleLevel():
    assert match_scope_pattern("src/main.py", "src/*.py") is True


def test_match_scope_pattern_returnsFalse_whenStarDoesNotCrossDirs():
    assert match_scope_pattern("src/sub/main.py", "src/*.py") is False


def test_match_scope_pattern_returnsTrue_whenDoublestarMatchesRecursive():
    assert match_scope_pattern("src/a/b/c.py", "src/**") is True


def test_match_scope_pattern_returnsTrue_whenTrailingSlashMatchesDirectFile():
    assert match_scope_pattern("src/main.py", "src/") is True


def test_match_scope_pattern_returnsTrue_whenTrailingSlashMatchesNestedFile():
    assert match_scope_pattern("src/sub/file.py", "src/") is True


def test_match_scope_pattern_returnsFalse_whenFileOutsideDir():
    assert match_scope_pattern("other/file.py", "src/") is False


def test_match_scope_pattern_returnsTrue_whenDoublestarInMiddleMatches():
    assert match_scope_pattern("src/a/b/main.py", "src/**/main.py") is True


def test_match_scope_pattern_returnsFalse_whenEmptyPattern():
    assert match_scope_pattern("a/b/c.py", "") is False


def test_match_scope_pattern_returnsTrue_whenRootDoublestarMatchesPy():
    assert match_scope_pattern("a/b/c.py", "**/*.py") is True


# ── compute_phase_sequence tests ─────────────────────────────────────────────


_STATIC_REGISTERED = [
    "0", "1.0", "1.1", "1.2", "1.3", "1.4",
    "2.0", "2.1",
    "4.0", "4.1", "4.2", "5",
]
_TEMPLATE_REGISTERED = [f"3.x.{k}" for k in range(5)]
_ALL_REGISTERED = _STATIC_REGISTERED + _TEMPLATE_REGISTERED


def _expected_with_execution(*item_numbers):
    """Build the full expected sequence for a plan with the given execution N values."""
    exec_ids = [f"3.{n}.{k}" for n in sorted(item_numbers) for k in range(5)]
    return (
        ["0", "1.0", "1.1", "1.2", "1.3", "1.4", "2.0", "2.1"]
        + exec_ids
        + ["4.0", "4.1", "4.2", "5"]
    )


def _plan_with_items(*item_numbers):
    """Build a minimal plan dict with execution items for given N values."""
    return {
        "execution": [
            {"id": f"3.{n}", "name": f"Sub-phase {n}", "tasks": []}
            for n in item_numbers
        ]
    }


def test_compute_phase_sequence_no_filter_returns_all():
    plan = _plan_with_items(1)
    result = compute_phase_sequence(plan, registered_phase_ids=_ALL_REGISTERED)
    assert result == _expected_with_execution(1)


def test_compute_phase_sequence_none_filter_returns_all():
    plan = _plan_with_items(1)
    result = compute_phase_sequence(plan, None, registered_phase_ids=_ALL_REGISTERED)
    assert result == _expected_with_execution(1)


def test_compute_phase_sequence_filters_disabled():
    plan = _plan_with_items(1)
    enabled = {"0", "1.0", "2.0", "4.2", "5"}
    result = compute_phase_sequence(plan, enabled, registered_phase_ids=_ALL_REGISTERED)
    assert set(result) == enabled
    assert "1.1" not in result
    assert "3.1.0" not in result
    assert "4.0" not in result


def test_compute_phase_sequence_preserves_order():
    plan = _plan_with_items(1, 2)
    full = compute_phase_sequence(plan, registered_phase_ids=_ALL_REGISTERED)
    enabled = {"0", "1.0", "2.0", "3.1.0", "4.0", "5"}
    filtered = compute_phase_sequence(plan, enabled, registered_phase_ids=_ALL_REGISTERED)
    full_positions = {phase: i for i, phase in enumerate(full)}
    filtered_positions = [full_positions[p] for p in filtered]
    assert filtered_positions == sorted(filtered_positions)


def test_compute_phase_sequence_with_plan_execution():
    """Execution phases 3.2.K appear between 2.1 and 4.0 when filtered."""
    plan = _plan_with_items(2)
    enabled = {"2.1", "3.2.0", "3.2.1", "3.2.2", "3.2.3", "3.2.4", "4.0"}
    result = compute_phase_sequence(plan, enabled, registered_phase_ids=_ALL_REGISTERED)
    idx_2_1 = result.index("2.1")
    idx_3_2_0 = result.index("3.2.0")
    idx_4_0 = result.index("4.0")
    assert idx_2_1 < idx_3_2_0 < idx_4_0


def test_compute_phase_sequence_empty_plan():
    """Missing or empty execution list returns only static phases."""
    for plan in ({}, {"execution": []}, None):
        result = compute_phase_sequence(plan, registered_phase_ids=_ALL_REGISTERED)
        assert result == _STATIC_REGISTERED


def test_compute_phase_sequence_no_registry_returns_empty():
    """When the caller injects no registry, the sequencer stays silent instead of guessing."""
    plan = _plan_with_items(1)
    assert compute_phase_sequence(plan) == []
    assert compute_phase_sequence(plan, {"0", "1.0"}) == []


def test_compute_phase_sequence_expands_multiple_execution_items():
    plan = _plan_with_items(1, 3)
    result = compute_phase_sequence(plan, registered_phase_ids=_ALL_REGISTERED)
    expected = _expected_with_execution(1, 3)
    assert result == expected


@pytest.mark.parametrize("enabled", [
    {"0", "1.0", "2.0", "4.2", "5"},
    {"0"},
    {"5"},
])
def test_compute_phase_sequence_filters_to_subset_parametrized(enabled):
    plan = _plan_with_items(1)
    result = compute_phase_sequence(plan, enabled, registered_phase_ids=_ALL_REGISTERED)
    unfiltered = compute_phase_sequence(plan, registered_phase_ids=_ALL_REGISTERED)
    assert all(p in enabled for p in result)
    assert all(p in result for p in enabled if p in unfiltered)
