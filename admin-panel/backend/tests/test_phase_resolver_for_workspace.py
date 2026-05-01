"""Tests for phase_resolver.resolve_for_workspace (sub-phase 3.6)."""
from datetime import datetime

import pytest

from core.db import get_db
from services import work_mode_service
from services.phase_resolver import resolve_for_workspace
from services.phase_settings import set_scope_settings


@pytest.fixture
def db(clean_db):
    conn = get_db()
    yield conn
    conn.close()


@pytest.fixture
def basic_mode_id(db):
    modes = work_mode_service.list_modes(db)
    return next(m for m in modes if m["name"] == "basic")["id"]


@pytest.fixture
def user_mode_with_disabled_phase(db):
    """User mode identical to basic but with 1.1 disabled."""
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated, phase_key

    canonical_ids = sorted(
        [pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)],
        key=phase_key,
    )
    phases = [
        {"phase_id": pid, "enabled": pid != "1.1", "position": pos}
        for pos, pid in enumerate(canonical_ids)
    ]
    return work_mode_service.create(db, name="no-research", phases=phases)


def _insert_phase_setting(db, scope_type, scope_id, phase_id, enabled):
    db.execute(
        "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (scope_type, scope_id, phase_id, 1 if enabled else 0, datetime.now().isoformat()),
    )
    db.commit()


# ── resolve_for_workspace ─────────────────────────────────────────────────────

def test_resolve_for_workspace_returns_basic_phases_when_no_overrides(
    db, project, workspace, basic_mode_id
):
    """Workspace assigned to basic with no scope overrides returns all canonical phases."""
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated

    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (basic_mode_id, workspace["id"]),
    )
    db.commit()

    phases = resolve_for_workspace(db, workspace["id"])

    canonical_ids = {pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)}
    assert set(phases) == canonical_ids


def test_workspace_override_disables_phase_baseline_enabled(db, project, workspace, basic_mode_id):
    """basic enables 1.1; workspace phase_settings disables 1.1 → 1.1 excluded."""
    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (basic_mode_id, workspace["id"]),
    )
    db.commit()

    _insert_phase_setting(db, "workspace", str(workspace["id"]), "1.1", False)

    phases = resolve_for_workspace(db, workspace["id"])

    assert "1.1" not in phases
    assert "1.0" in phases


def test_project_override_disables_phase_baseline_enabled(db, project, workspace, basic_mode_id):
    """basic enables 1.2; project phase_settings disables 1.2 → 1.2 excluded."""
    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (basic_mode_id, workspace["id"]),
    )
    db.commit()

    _insert_phase_setting(db, "project", str(project["id"]), "1.2", False)

    phases = resolve_for_workspace(db, workspace["id"])

    assert "1.2" not in phases


def test_workspace_override_re_enables_phase_baseline_disabled(
    db, project, workspace, user_mode_with_disabled_phase
):
    """User mode disables 1.1; workspace scope re-enables 1.1 → 1.1 included."""
    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (user_mode_with_disabled_phase["id"], workspace["id"]),
    )
    db.commit()

    _insert_phase_setting(db, "workspace", str(workspace["id"]), "1.1", True)

    phases = resolve_for_workspace(db, workspace["id"])

    assert "1.1" in phases


def test_workspace_override_beats_project_override(db, project, workspace, basic_mode_id):
    """Project disables 1.3; workspace enables 1.3 → 1.3 included (workspace wins)."""
    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (basic_mode_id, workspace["id"]),
    )
    db.commit()

    _insert_phase_setting(db, "project", str(project["id"]), "1.3", False)
    _insert_phase_setting(db, "workspace", str(workspace["id"]), "1.3", True)

    phases = resolve_for_workspace(db, workspace["id"])

    assert "1.3" in phases


def test_resolve_for_workspace_falls_back_to_basic_when_work_mode_id_null(
    db, project, workspace
):
    """Workspace with work_mode_id=NULL falls back to basic mode (defensive fallback)."""
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated

    db.execute(
        "UPDATE workspaces SET work_mode_id = NULL WHERE id = ?",
        (workspace["id"],),
    )
    db.commit()

    phases = resolve_for_workspace(db, workspace["id"])

    canonical_ids = {pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)}
    assert set(phases) == canonical_ids


def test_resolve_for_workspace_returns_empty_for_unknown_workspace(db):
    """Unknown workspace_id returns empty list without raising."""
    phases = resolve_for_workspace(db, 999999)
    assert phases == []
