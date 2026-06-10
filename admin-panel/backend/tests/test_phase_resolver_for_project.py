"""Tests for phase_resolver.resolve_for_project.

The project-level resolver starts from the registered canonical phase set and
layers device- then project-scope overrides on top. Workspace-scope overrides
are explicitly excluded — they would render the wrong skill for projects
without a workspace in scope.
"""

import pytest

from core.db import get_db
from services.phase_resolver import resolve_for_project
from services.phase_settings import set_scope_settings


@pytest.fixture
def db(clean_db):
    conn = get_db()
    yield conn
    conn.close()


def _canonical_registered_ids():
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated

    return {pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)}


_TEMPLATED_EXECUTION_IDS = ["3.x.0", "3.x.1", "3.x.2", "3.x.3", "3.x.4"]


# ── Baseline ───────────────────────────────────────────────────────────────────


def test_returns_canonical_baseline_when_no_overrides(db, project):
    """With no scope overrides, the resolver returns every canonical phase."""
    phases = resolve_for_project(db, project["id"])
    assert set(phases) == _canonical_registered_ids()


def test_returns_phases_in_canonical_order(db, project):
    """The resolver returns phases sorted by phase_key."""
    from core.phase import phase_key

    phases = resolve_for_project(db, project["id"])

    assert phases == sorted(phases, key=phase_key)


# ── Project-scope overrides ────────────────────────────────────────────────────


def test_project_override_disables_phase(db, project):
    """A project-scope override with ``False`` drops the phase from the result."""
    set_scope_settings(db, "project", str(project["id"]), {"1.1": False})
    db.commit()

    phases = resolve_for_project(db, project["id"])
    assert "1.1" not in phases
    assert "1.0" in phases  # sanity, unrelated phase still present


def test_project_override_enabling_phase_is_noop_when_already_baseline_enabled(db, project):
    """Re-enabling a baseline-on phase via overrides is a no-op."""
    set_scope_settings(db, "project", str(project["id"]), {"1.1": True})
    db.commit()

    phases = resolve_for_project(db, project["id"])
    assert "1.1" in phases


# ── Device-scope overrides ─────────────────────────────────────────────────────


def test_device_override_disables_phase(db, project):
    """A device-level override applies project-side too."""
    set_scope_settings(db, "device", "", {"4.0": False})
    db.commit()

    phases = resolve_for_project(db, project["id"])
    assert "4.0" not in phases


def test_project_override_beats_device_override(db, project):
    """Device disables 1.3; project re-enables 1.3 → present (project wins)."""
    set_scope_settings(db, "device", "", {"1.3": False})
    set_scope_settings(db, "project", str(project["id"]), {"1.3": True})
    db.commit()

    phases = resolve_for_project(db, project["id"])
    assert "1.3" in phases


# ── Workspace overrides are excluded ───────────────────────────────────────────


def test_workspace_override_is_ignored(db, project, workspace):
    """resolve_for_project explicitly ignores workspace-scope overrides."""
    set_scope_settings(db, "workspace", str(workspace["id"]), {"1.1": False})
    db.commit()

    phases = resolve_for_project(db, project["id"])
    assert "1.1" in phases


# ── include_templated opt-in ────────────────────────────────────────────────────


def test_default_call_excludes_templated_execution_ids(db, project):
    """The default (include_templated=False) result carries no 3.x.K ids."""
    phases = resolve_for_project(db, project["id"])

    assert not any(pid in phases for pid in _TEMPLATED_EXECUTION_IDS)


def test_include_templated_matches_default_plus_templated_ids(db, project):
    """include_templated=True returns the default set plus the 3.x.K family."""
    default_phases = resolve_for_project(db, project["id"])

    templated_phases = resolve_for_project(db, project["id"], include_templated=True)

    assert set(templated_phases) == set(default_phases) | set(_TEMPLATED_EXECUTION_IDS)


def test_include_templated_places_execution_ids_between_2x_and_4_0(db, project):
    """The 3.x.0..3.x.4 block lands after 2.0 and before 4.0, in order."""
    phases = resolve_for_project(db, project["id"], include_templated=True)

    assert phases[phases.index("2.0") + 1 : phases.index("4.0")] == _TEMPLATED_EXECUTION_IDS


def test_include_templated_result_is_sorted_by_phase_key(db, project):
    """The include_templated result stays in canonical phase_key order."""
    from core.phase import phase_key

    phases = resolve_for_project(db, project["id"], include_templated=True)

    assert phases == sorted(phases, key=phase_key)


def test_include_templated_honors_scope_override_on_templated_id(db, project):
    """A project override on a literal 3.x.K id drops it from the templated result."""
    set_scope_settings(db, "project", str(project["id"]), {"3.x.2": False})
    db.commit()

    phases = resolve_for_project(db, project["id"], include_templated=True)

    assert "3.x.2" not in phases
    assert "3.x.0" in phases  # sibling template still present
