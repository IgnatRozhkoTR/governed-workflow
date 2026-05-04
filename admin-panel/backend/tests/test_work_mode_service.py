"""Tests for services.work_mode_service (unit 3.6)."""
import pytest

from core.db import get_db
from services import work_mode_service
from services.work_mode_service import WorkModeServiceError


@pytest.fixture
def db(clean_db):
    conn = get_db()
    yield conn
    conn.close()


@pytest.fixture
def user_mode(db):
    """Create a throwaway user mode for tests that need a pre-existing mode."""
    mode = work_mode_service.create(
        db,
        name="test-mode",
        description="A test mode",
        phases=[{"phase_id": "1.1", "enabled": True, "position": 0}],
    )
    return mode


# ── Seeding ───────────────────────────────────────────────────────────────────

def test_basic_mode_seeded_with_origin_system(db):
    modes = work_mode_service.list_modes(db)
    basic = next((m for m in modes if m["name"] == "basic"), None)
    assert basic is not None
    assert basic["origin"] == "system"


def test_basic_mode_includes_all_canonical_phases(db):
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated

    modes = work_mode_service.list_modes(db)
    basic = next(m for m in modes if m["name"] == "basic")

    phase_ids_in_basic = {p["phase_id"] for p in basic["phases"]}
    canonical_ids = {pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)}

    for canonical_id in canonical_ids:
        assert canonical_id in phase_ids_in_basic, (
            f"Canonical phase {canonical_id!r} missing from basic mode phases"
        )
    for entry in basic["phases"]:
        assert entry["enabled"] is True, (
            f"Basic mode phase {entry['phase_id']!r} should be enabled=True"
        )


# ── create ────────────────────────────────────────────────────────────────────

def test_create_user_mode_inserts_rows(db):
    phases = [
        {"phase_id": "1.1", "enabled": True, "position": 0},
        {"phase_id": "1.2", "enabled": False, "position": 1},
    ]
    mode = work_mode_service.create(db, name="my-mode", description="desc", phases=phases)

    assert mode["id"] is not None
    assert mode["name"] == "my-mode"
    assert mode["description"] == "desc"
    assert mode["origin"] == "user"
    phase_map = {p["phase_id"]: p for p in mode["phases"]}
    assert phase_map["1.1"]["enabled"] is True
    assert phase_map["1.2"]["enabled"] is False


def test_create_raises_name_collision_on_duplicate(db):
    work_mode_service.create(db, name="dup-mode")

    with pytest.raises(WorkModeServiceError) as exc_info:
        work_mode_service.create(db, name="dup-mode")

    assert exc_info.value.code == "name_collision"


def test_create_raises_invalid_name_on_bad_pattern(db):
    with pytest.raises(WorkModeServiceError) as exc_info:
        work_mode_service.create(db, name="has spaces in it")

    assert exc_info.value.code == "invalid_name"


def test_create_raises_invalid_name_on_uppercase(db):
    with pytest.raises(WorkModeServiceError) as exc_info:
        work_mode_service.create(db, name="Upper-Case")

    assert exc_info.value.code == "invalid_name"


# ── get ───────────────────────────────────────────────────────────────────────

def test_get_returns_mode_with_phases(db, user_mode):
    fetched = work_mode_service.get(db, user_mode["id"])

    assert fetched["id"] == user_mode["id"]
    assert fetched["name"] == user_mode["name"]
    assert len(fetched["phases"]) == 1
    assert fetched["phases"][0]["phase_id"] == "1.1"


def test_get_raises_not_found_for_unknown_id(db):
    with pytest.raises(WorkModeServiceError) as exc_info:
        work_mode_service.get(db, 999999)

    assert exc_info.value.code == "not_found"


# ── update ────────────────────────────────────────────────────────────────────

def test_update_sparse_preserves_unmodified_fields(db, user_mode):
    updated = work_mode_service.update(db, user_mode["id"], description="new desc")

    assert updated["name"] == user_mode["name"]
    assert updated["description"] == "new desc"
    assert len(updated["phases"]) == len(user_mode["phases"])


def test_update_replaces_phases_when_supplied(db, user_mode):
    new_phases = [
        {"phase_id": "4.0", "enabled": True, "position": 0},
        {"phase_id": "4.1", "enabled": False, "position": 1},
    ]
    updated = work_mode_service.update(db, user_mode["id"], phases=new_phases)

    phase_ids = {p["phase_id"] for p in updated["phases"]}
    assert phase_ids == {"4.0", "4.1"}
    assert "1.1" not in phase_ids


def test_update_system_mode_raises_system_immutable(db):
    modes = work_mode_service.list_modes(db)
    basic = next(m for m in modes if m["name"] == "basic")

    with pytest.raises(WorkModeServiceError) as exc_info:
        work_mode_service.update(db, basic["id"], description="hacked")

    assert exc_info.value.code == "system_immutable"


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_user_mode_succeeds(db, user_mode):
    result = work_mode_service.delete(db, user_mode["id"])

    assert result is True

    with pytest.raises(WorkModeServiceError) as exc_info:
        work_mode_service.get(db, user_mode["id"])
    assert exc_info.value.code == "not_found"


def test_delete_raises_system_immutable_for_system_mode(db):
    modes = work_mode_service.list_modes(db)
    basic = next(m for m in modes if m["name"] == "basic")

    with pytest.raises(WorkModeServiceError) as exc_info:
        work_mode_service.delete(db, basic["id"])

    assert exc_info.value.code == "system_immutable"


# ── assign ────────────────────────────────────────────────────────────────────

def test_assign_sets_work_mode_id_does_not_change_phase_column(db, project, workspace):
    modes = work_mode_service.list_modes(db)
    basic = next(m for m in modes if m["name"] == "basic")

    original_phase = db.execute(
        "SELECT phase FROM workspaces WHERE id = ?", (workspace["id"],)
    ).fetchone()["phase"]

    result = work_mode_service.assign(db, workspace["id"], basic["id"])

    assert result["workspace_id"] == workspace["id"]
    assert result["mode_id"] == basic["id"]
    assert result["mode_name"] == "basic"
    assert "assigned_at" in result and isinstance(result["assigned_at"], str)

    row = db.execute(
        "SELECT phase, work_mode_id FROM workspaces WHERE id = ?", (workspace["id"],)
    ).fetchone()
    assert row["work_mode_id"] == basic["id"]
    assert row["phase"] == original_phase


def test_list_modes_includes_used_by_count(db, user_mode, workspace):
    work_mode_service.assign(db, workspace["id"], user_mode["id"])

    modes = work_mode_service.list_modes(db)

    target = next(m for m in modes if m["id"] == user_mode["id"])
    assert "used_by_count" in target
    assert target["used_by_count"] == 1


def test_list_modes_used_by_count_is_zero_for_unassigned_mode(db, user_mode):
    modes = work_mode_service.list_modes(db)

    target = next(m for m in modes if m["id"] == user_mode["id"])
    assert target["used_by_count"] == 0


def test_get_mode_includes_used_by_count(db, user_mode, workspace):
    work_mode_service.assign(db, workspace["id"], user_mode["id"])

    fetched = work_mode_service.get(db, user_mode["id"])

    assert fetched["used_by_count"] == 1


# ── apply ─────────────────────────────────────────────────────────────────────

def test_apply_returns_effective_phase_list_does_not_change_phase_column(db, project, workspace):
    original_phase = db.execute(
        "SELECT phase FROM workspaces WHERE id = ?", (workspace["id"],)
    ).fetchone()["phase"]

    result = work_mode_service.apply(db, workspace["id"])

    assert "effective_phases" in result
    assert isinstance(result["effective_phases"], list)
    assert len(result["effective_phases"]) > 0

    row = db.execute(
        "SELECT phase FROM workspaces WHERE id = ?", (workspace["id"],)
    ).fetchone()
    assert row["phase"] == original_phase
