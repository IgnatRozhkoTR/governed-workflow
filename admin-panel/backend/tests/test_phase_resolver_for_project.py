"""Tests for phase_resolver.resolve_for_project (sub-phase 3.1).

The project-level resolver applies the basic mode baseline and layers device-
then project-scope overrides on top. Workspace-scope overrides are explicitly
excluded — they would render the wrong skill for projects without a workspace
in scope.
"""

from datetime import datetime

import pytest

from core.db import get_db
from services.phase_resolver import resolve_for_project
from services.phase_settings import set_scope_settings


@pytest.fixture
def db(clean_db):
    conn = get_db()
    yield conn
    conn.close()


def _basic_canonical_ids():
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated

    return {pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)}


# ── Baseline ───────────────────────────────────────────────────────────────────


def test_returns_basic_baseline_when_no_overrides(db, project):
    """With no scope overrides, the resolver returns the full basic-mode sequence."""
    phases = resolve_for_project(db, project["id"])
    assert set(phases) == _basic_canonical_ids()


def test_returns_phases_in_position_order(db, project):
    """The resolver preserves the ``position`` order recorded on the basic mode."""
    from core.phase import phase_key

    phases = resolve_for_project(db, project["id"])

    # The basic mode is seeded with canonical ids in canonical order; the
    # returned list must already be sorted by phase_key.
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


# ── Failure modes ──────────────────────────────────────────────────────────────


def test_returns_empty_when_basic_mode_missing(db, project):
    """If the seeded basic mode is removed, the resolver returns []."""
    db.execute("DELETE FROM work_mode_phases WHERE work_mode_id IN "
               "(SELECT id FROM work_modes WHERE name = 'basic')")
    db.execute("DELETE FROM work_modes WHERE name = 'basic'")
    db.commit()

    assert resolve_for_project(db, project["id"]) == []

    # Restore the basic mode so other tests don't see a dirty registry.
    from services import work_mode_service
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated, phase_key

    canonical_ids = sorted(
        [pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)],
        key=phase_key,
    )
    work_mode_service.create(
        db,
        name="basic",
        phases=[{"phase_id": pid, "enabled": True, "position": i}
                for i, pid in enumerate(canonical_ids)],
    )
    # Mark as system origin so clean_db doesn't try to delete it.
    db.execute("UPDATE work_modes SET origin = 'system' WHERE name = 'basic'")
    db.commit()
