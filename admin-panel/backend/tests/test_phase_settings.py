"""Tests for phase_settings service and phase_resolver."""
import pytest

from services.phase_settings import (
    ALWAYS_ON_PHASE_IDS,
    is_always_on,
    get_scope_settings,
    set_scope_settings,
)
from services.phase_resolver import resolve_enabled_phases
from core.db import get_db


@pytest.fixture(autouse=True)
def clean_phase_settings(clean_db):
    yield
    db = get_db()
    db.execute("DELETE FROM phase_settings")
    db.commit()
    db.close()


@pytest.fixture
def db(clean_phase_settings):
    conn = get_db()
    yield conn
    conn.close()


def test_always_on_phase_ids_is_empty():
    assert ALWAYS_ON_PHASE_IDS == frozenset()


@pytest.mark.parametrize("phase_id", ["0", "1.0", "2.0", "4.2", "5"])
def test_is_always_on_returns_false_for_core_phases(phase_id):
    assert is_always_on(phase_id) is False


@pytest.mark.parametrize("phase_id", ["3.1.3", "3.2.3", "3.99.3"])
def test_is_always_on_returns_false_for_commit_gate_pattern(phase_id):
    assert is_always_on(phase_id) is False


def test_is_always_on_returns_false_for_commit_gate_template():
    assert is_always_on("3.x.3") is False


@pytest.mark.parametrize("phase_id", ["1.1", "1.2", "1.3", "1.4", "4.0", "4.1", "3.1.0", "3.1.4"])
def test_is_always_on_returns_false_for_toggleable_phases(phase_id):
    assert is_always_on(phase_id) is False


def test_basic_mode_includes_core_phases_enabled(db):
    """The basic system mode has all core phase ids with enabled=1."""
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated

    rows = db.execute(
        "SELECT wmp.phase_id, wmp.enabled "
        "FROM work_mode_phases wmp "
        "JOIN work_modes wm ON wm.id = wmp.work_mode_id "
        "WHERE wm.name = 'basic'"
    ).fetchall()
    basic_phases = {row["phase_id"]: bool(row["enabled"]) for row in rows}

    canonical_ids = [pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)]
    for phase_id in canonical_ids:
        assert phase_id in basic_phases, f"phase {phase_id} missing from basic mode"
        assert basic_phases[phase_id] is True, f"phase {phase_id} should be enabled in basic mode"


def test_set_scope_settings_upserts_rows(db):
    set_scope_settings(db, "device", "", {"1.1": False, "1.2": False})
    db.commit()

    rows = db.execute(
        "SELECT phase_id, enabled FROM phase_settings WHERE scope_type='device' AND scope_id='' ORDER BY phase_id"
    ).fetchall()
    assert len(rows) == 2
    assert all(row["enabled"] == 0 for row in rows)


def test_set_scope_settings_accepts_formerly_always_on_disable(db):
    """Disabling a formerly-pinned phase now succeeds — basic mode still pins it in the baseline."""
    set_scope_settings(db, "device", "", {"0": False})
    db.commit()

    result = get_scope_settings(db, "device", "")
    assert result["0"] is False


@pytest.mark.parametrize("scope_type", ["device", "project", "workspace"])
def test_set_scope_settings_accepts_any_phase_disable(db, scope_type):
    """set_scope_settings no longer rejects disabling any phase — ValueError is not raised."""
    set_scope_settings(db, scope_type, "x", {"0": False})
    db.commit()

    result = get_scope_settings(db, scope_type, "x")
    assert result["0"] is False


def test_set_scope_settings_allows_phase_enable(db):
    set_scope_settings(db, "device", "", {"0": True})
    db.commit()

    result = get_scope_settings(db, "device", "")
    assert result["0"] is True


@pytest.mark.parametrize("scope_type", ["user", ""])
def test_set_scope_settings_invalid_scope_type(db, scope_type):
    with pytest.raises(ValueError):
        set_scope_settings(db, scope_type, "", {"1.1": True})


def test_get_scope_settings_returns_mapping(db):
    set_scope_settings(db, "project", "proj-1", {"1.1": False, "4.0": True})
    db.commit()

    result = get_scope_settings(db, "project", "proj-1")
    assert result == {"1.1": False, "4.0": True}


def test_get_scope_settings_empty_when_unset(db):
    result = get_scope_settings(db, "workspace", "ws-999")
    assert result == {}


def test_resolve_empty_uses_default_all_on(db):
    all_phases = {"0", "1.0", "1.1", "4.0"}
    result = resolve_enabled_phases(db, None, None, all_phases)
    assert result == all_phases


def test_resolve_device_disables(db):
    set_scope_settings(db, "device", "", {"1.1": False})
    db.commit()

    result = resolve_enabled_phases(db, None, None, {"0", "1.0", "1.1", "4.0"})
    assert "1.1" not in result
    assert "1.0" in result


def test_resolve_workspace_overrides_project(db):
    set_scope_settings(db, "project", "p1", {"1.1": False})
    set_scope_settings(db, "workspace", "w1", {"1.1": True})
    db.commit()

    result = resolve_enabled_phases(db, "w1", "p1", {"0", "1.0", "1.1"})
    assert "1.1" in result


def test_resolve_project_overrides_device(db):
    set_scope_settings(db, "device", "", {"1.1": False})
    set_scope_settings(db, "project", "p2", {"1.1": True})
    db.commit()

    result = resolve_enabled_phases(db, None, "p2", {"0", "1.0", "1.1"})
    assert "1.1" in result


def test_resolve_formerly_always_on_can_be_overridden_by_scope(db):
    """A workspace-level disable row now takes effect for a formerly-pinned phase."""
    from datetime import datetime
    db.execute(
        "INSERT INTO phase_settings (scope_type, scope_id, phase_id, enabled, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("device", "", "0", 0, datetime.now().isoformat()),
    )
    db.commit()

    result = resolve_enabled_phases(db, None, None, {"0", "1.1"})
    assert "0" not in result


def test_resolve_workspace_disables(db):
    set_scope_settings(db, "workspace", "w2", {"4.0": False})
    db.commit()

    result = resolve_enabled_phases(db, "w2", None, {"0", "1.0", "4.0"})
    assert "4.0" not in result
    assert "0" in result
