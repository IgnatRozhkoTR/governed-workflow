"""End-to-end integration tests for work modes + phase resolution.

Covers:
- The seeded ``basic`` system mode pinning the canonical phase sequence.
- User modes turning every canonical phase off / re-enabling phases turned off
  by other modes.
- The override cascade: workspace > project > device > mode baseline.
- Behavior preservation: workspaces with no phase_settings inherit basic.
- System-mode immutability via the service and the REST layer.
- The full create -> assign -> apply lifecycle resolves to the expected
  effective phases.
- Switching work mode mid-task does not mutate ``workspaces.phase``.
"""
import pytest

from advance.phases import PHASE_REGISTRY
from core.db import get_db
from core.phase import is_templated, phase_key
from services import work_mode_service
from services.phase_resolver import resolve_for_workspace
from services.phase_settings import set_scope_settings
from services.work_mode_service import WorkModeServiceError


CANONICAL_PHASE_IDS: list[str] = sorted(
    [pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)],
    key=phase_key,
)


@pytest.fixture
def db(clean_db):
    conn = get_db()
    yield conn
    conn.close()


@pytest.fixture
def basic_mode(db):
    return next(m for m in work_mode_service.list_modes(db) if m["name"] == "basic")


def _assign_basic(db, workspace_id: int, basic_mode_id: int) -> None:
    db.execute(
        "UPDATE workspaces SET work_mode_id = ? WHERE id = ?",
        (basic_mode_id, workspace_id),
    )
    db.commit()


def _build_phases_with_disabled(disabled_phase_id: str) -> list[dict]:
    """Build a phases list mirroring basic, with one phase id disabled."""
    return [
        {
            "phase_id": pid,
            "enabled": pid != disabled_phase_id,
            "position": pos,
        }
        for pos, pid in enumerate(CANONICAL_PHASE_IDS)
    ]


# ── Phase toggle smoke ────────────────────────────────────────────────────────


def test_basic_mode_initially_pins_all_canonical_phases(db, basic_mode):
    phase_ids_in_basic = {p["phase_id"] for p in basic_mode["phases"]}

    assert set(CANONICAL_PHASE_IDS) <= phase_ids_in_basic
    for entry in basic_mode["phases"]:
        if entry["phase_id"] in CANONICAL_PHASE_IDS:
            assert entry["enabled"] is True


@pytest.mark.parametrize("phase_to_disable", CANONICAL_PHASE_IDS)
def test_user_mode_can_disable_every_canonical_phase(
    db, project, workspace, phase_to_disable
):
    """For every canonical phase, a user mode that disables exactly that phase
    excludes it from the resolved list while keeping all other canonical phases."""
    phases = _build_phases_with_disabled(phase_to_disable)
    safe_name = phase_to_disable.replace(".", "-")
    user_mode = work_mode_service.create(
        db,
        name=f"disable-{safe_name}",
        description=f"basic minus {phase_to_disable}",
        phases=phases,
    )

    work_mode_service.assign(db, workspace["id"], user_mode["id"])

    effective = resolve_for_workspace(db, workspace["id"])

    assert phase_to_disable not in effective
    expected_remaining = [pid for pid in CANONICAL_PHASE_IDS if pid != phase_to_disable]
    assert set(effective) == set(expected_remaining)


def test_user_mode_can_re_enable_phase_disabled_in_other_modes(
    db, project, workspace
):
    """Mode A disables 1.1; Mode B enables 1.1; assigning B to the workspace
    causes 1.1 to appear in the effective list."""
    phases_a = _build_phases_with_disabled("1.1")
    phases_b = [
        {"phase_id": pid, "enabled": True, "position": pos}
        for pos, pid in enumerate(CANONICAL_PHASE_IDS)
    ]

    work_mode_service.create(db, name="mode-a-no-research", phases=phases_a)
    mode_b = work_mode_service.create(db, name="mode-b-with-research", phases=phases_b)

    work_mode_service.assign(db, workspace["id"], mode_b["id"])

    effective = resolve_for_workspace(db, workspace["id"])

    assert "1.1" in effective


# ── Override-cascade ──────────────────────────────────────────────────────────


def test_workspace_override_disables_phase_pinned_by_basic_mode(
    db, project, workspace, basic_mode
):
    """basic enables 1.1; a workspace-level phase_settings row disabling 1.1
    excludes it from the effective list."""
    _assign_basic(db, workspace["id"], basic_mode["id"])

    set_scope_settings(db, "workspace", str(workspace["id"]), {"1.1": False})
    db.commit()

    effective = resolve_for_workspace(db, workspace["id"])

    assert "1.1" not in effective
    assert "1.0" in effective


def test_project_override_disables_phase_pinned_by_basic_mode(
    db, project, workspace, basic_mode
):
    _assign_basic(db, workspace["id"], basic_mode["id"])

    set_scope_settings(db, "project", str(project["id"]), {"1.2": False})
    db.commit()

    effective = resolve_for_workspace(db, workspace["id"])

    assert "1.2" not in effective


def test_workspace_override_beats_project_override(
    db, project, workspace, basic_mode
):
    """project disables 4.0; workspace re-enables 4.0 → workspace wins."""
    _assign_basic(db, workspace["id"], basic_mode["id"])

    set_scope_settings(db, "project", str(project["id"]), {"4.0": False})
    set_scope_settings(db, "workspace", str(workspace["id"]), {"4.0": True})
    db.commit()

    effective = resolve_for_workspace(db, workspace["id"])

    assert "4.0" in effective


def test_workspace_override_beats_device_override(
    db, project, workspace, basic_mode
):
    """device disables 4.1; workspace re-enables 4.1 → workspace wins."""
    _assign_basic(db, workspace["id"], basic_mode["id"])

    set_scope_settings(db, "device", "", {"4.1": False})
    set_scope_settings(db, "workspace", str(workspace["id"]), {"4.1": True})
    db.commit()

    effective = resolve_for_workspace(db, workspace["id"])

    assert "4.1" in effective


def test_user_mode_re_enabling_disabled_phase_takes_effect_without_overrides(
    db, project, workspace
):
    """User mode rebaseline beats the absence of any scope override — i.e.
    selecting a mode that enables 1.1 lets 1.1 appear without any extra rows."""
    phases = [
        {"phase_id": pid, "enabled": True, "position": pos}
        for pos, pid in enumerate(CANONICAL_PHASE_IDS)
    ]
    user_mode = work_mode_service.create(db, name="mode-everything-on", phases=phases)

    work_mode_service.assign(db, workspace["id"], user_mode["id"])

    effective = resolve_for_workspace(db, workspace["id"])

    assert "1.1" in effective


# ── Behavior preservation ─────────────────────────────────────────────────────


def test_existing_workspace_with_no_phase_settings_inherits_basic(
    db, project, workspace
):
    """A workspace with no scope overrides resolves to the canonical sequence."""
    effective = resolve_for_workspace(db, workspace["id"])

    assert set(effective) == set(CANONICAL_PHASE_IDS)
    sorted_canonical = sorted(CANONICAL_PHASE_IDS, key=phase_key)
    assert effective == sorted_canonical


def test_basic_mode_cannot_be_deleted_via_service(db, basic_mode):
    with pytest.raises(WorkModeServiceError) as exc_info:
        work_mode_service.delete(db, basic_mode["id"])

    assert exc_info.value.code == "system_immutable"


def test_basic_mode_cannot_be_deleted_via_REST(client, db):
    basic = next(m for m in work_mode_service.list_modes(db) if m["name"] == "basic")

    resp = client.delete(f"/api/work-modes/{basic['id']}")

    assert resp.status_code == 409
    body = resp.get_json()
    assert body["code"] == "system_immutable"


# ── End-to-end mode lifecycle ─────────────────────────────────────────────────


def test_create_assign_apply_resolves_correctly(db, project, workspace):
    """create user mode 'minimal' enabling [0, 1.0, 5]; assign; apply resolves
    to those three in canonical order."""
    enabled_set = {"0", "1.0", "5"}
    phases = [
        {"phase_id": pid, "enabled": pid in enabled_set, "position": pos}
        for pos, pid in enumerate(CANONICAL_PHASE_IDS)
    ]
    minimal = work_mode_service.create(
        db,
        name="minimal",
        description="only init, assessment, done",
        phases=phases,
    )

    work_mode_service.assign(db, workspace["id"], minimal["id"])
    result = work_mode_service.apply(db, workspace["id"])

    assert result["mode_id"] == minimal["id"]
    assert result["mode_name"] == "minimal"
    assert result["effective_phases"] == ["0", "1.0", "5"]


def test_changing_mode_mid_task_does_not_mutate_workspace_phase(
    db, project, workspace
):
    """workspace.phase is set to '4.0'; assigning a mode that disables 4.0
    leaves workspace.phase unchanged but resolve excludes 4.0."""
    db.execute(
        "UPDATE workspaces SET phase = '4.0' WHERE id = ?",
        (workspace["id"],),
    )
    db.commit()

    phases = _build_phases_with_disabled("4.0")
    no_blind_review = work_mode_service.create(
        db,
        name="no-blind-review",
        phases=phases,
    )

    work_mode_service.assign(db, workspace["id"], no_blind_review["id"])

    row = db.execute(
        "SELECT phase, work_mode_id FROM workspaces WHERE id = ?",
        (workspace["id"],),
    ).fetchone()
    assert row["phase"] == "4.0"
    assert row["work_mode_id"] == no_blind_review["id"]

    effective = resolve_for_workspace(db, workspace["id"])
    assert "4.0" not in effective
    assert "4.1" in effective
