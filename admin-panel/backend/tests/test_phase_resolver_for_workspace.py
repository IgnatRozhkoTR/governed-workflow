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


# ── Templated execution phases ───────────────────────────────────────────────


def test_workspace_scope_override_disables_concrete_execution_phase(
    db, project, workspace, basic_mode_id
):
    """A 3.5.3 scope override is honored even though only 3.x.3 lives in the mode.

    Regression for finding 919: ``resolve_for_workspace`` previously dropped
    scope-override entries pointing at concrete ``3.N.K`` ids because they
    were missing from the universe.
    """
    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (basic_mode_id, workspace["id"]),
    )
    db.commit()

    _insert_phase_setting(db, "workspace", str(workspace["id"]), "3.5.3", False)

    phases = resolve_for_workspace(db, workspace["id"])

    assert "3.5.3" not in phases


def test_workspace_scope_override_enables_concrete_execution_phase(
    db, project, workspace, basic_mode_id
):
    """A workspace can re-enable a single concrete 3.N.K via scope settings.

    The mode does not list the concrete id; the templated parent governs the
    default (enabled, in basic). The workspace-level row enables the id and
    it must appear in the resolved sequence.
    """
    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (basic_mode_id, workspace["id"]),
    )
    db.commit()

    _insert_phase_setting(db, "workspace", str(workspace["id"]), "3.7.0", True)

    phases = resolve_for_workspace(db, workspace["id"])

    assert "3.7.0" in phases


def test_resolve_for_workspace_inherits_templated_disable_from_mode(
    db, project, workspace
):
    """A mode disabling 3.x.3 cascades to every concrete 3.N.3 toggled via overrides."""
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated, phase_key

    canonical_ids = sorted(
        [pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)],
        key=phase_key,
    )
    phases = [
        {"phase_id": pid, "enabled": True, "position": pos}
        for pos, pid in enumerate(canonical_ids)
    ]
    phases.append(
        {"phase_id": "3.x.3", "enabled": False, "position": len(canonical_ids)}
    )
    mode = work_mode_service.create(db, name="no-commit-gate", phases=phases)

    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (mode["id"], workspace["id"]),
    )
    db.commit()

    _insert_phase_setting(db, "workspace", str(workspace["id"]), "3.4.3", True)
    resolved_with_override = resolve_for_workspace(db, workspace["id"])
    assert "3.4.3" in resolved_with_override

    db.execute(
        "DELETE FROM phase_settings WHERE phase_id = ?",
        ("3.4.3",),
    )
    db.commit()

    _insert_phase_setting(db, "workspace", str(workspace["id"]), "3.4.3", False)
    resolved_without = resolve_for_workspace(db, workspace["id"])
    assert "3.4.3" not in resolved_without


# ── Diagnostic logging ───────────────────────────────────────────────────────


def test_resolve_logs_warning_for_unknown_phase_id_in_mode_row(
    db, project, workspace, caplog
):
    """An orphaned ``work_mode_phases`` row referencing an unregistered phase
    id is logged at warning level instead of being silently filtered."""
    import logging

    user_mode = work_mode_service.create(
        db,
        name="known-mode-only",
        phases=[{"phase_id": "1.1", "enabled": True, "position": 0}],
    )
    db.execute(
        "INSERT INTO work_mode_phases (work_mode_id, phase_id, enabled, position) "
        "VALUES (?, ?, 1, 99)",
        (user_mode["id"], "9.9.9"),
    )
    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (user_mode["id"], workspace["id"]),
    )
    db.commit()

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="services.phase_resolver"):
        resolve_for_workspace(db, workspace["id"])

    matching = [r for r in caplog.records if "9.9.9" in r.getMessage()]
    assert matching, f"Expected warning about '9.9.9'; got: {[r.getMessage() for r in caplog.records]}"


# ── Resolver agreement ───────────────────────────────────────────────────────


def test_resolve_for_workspace_agrees_with_resolve_enabled_phases_on_concrete_3nk(
    db, project, workspace, basic_mode_id
):
    """Both resolvers must yield the same disabled set for a 3.N.K override."""
    from services.phase_resolver import resolve_enabled_phases

    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (basic_mode_id, workspace["id"]),
    )
    db.commit()

    _insert_phase_setting(db, "workspace", str(workspace["id"]), "3.2.3", False)

    resolve_for_ws_phases = set(resolve_for_workspace(db, workspace["id"]))

    universe = set(resolve_for_ws_phases) | {"3.2.3"}
    legacy_enabled = resolve_enabled_phases(
        db, workspace["id"], project["id"], universe
    )

    assert ("3.2.3" in resolve_for_ws_phases) == ("3.2.3" in legacy_enabled)
    assert "3.2.3" not in resolve_for_ws_phases
    assert "3.2.3" not in legacy_enabled
