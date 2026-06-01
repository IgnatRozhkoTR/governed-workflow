"""Tests for advance_mode_service: get_mode_for_boundary, set_modes, seed_default_modes."""
import pytest

from core.db import get_db
from services.advance_mode_service import (
    AdvanceModeServiceError,
    DEFAULT_MODES,
    get_mode_for_boundary,
    list_modes,
    seed_default_modes,
    set_modes,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _insert_project(db, project_id: str) -> None:
    db.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", "/tmp", "2024-01-01T00:00:00"),
    )
    db.commit()


# ── get_mode_for_boundary ─────────────────────────────────────────────────────


def test_get_mode_for_boundary_returns_exact_match():
    db = get_db()
    try:
        _insert_project(db, "p-exact")
        set_modes(db, "p-exact", {"2": "compact"})

        result = get_mode_for_boundary(db, "p-exact", "2")
    finally:
        db.close()

    assert result == "compact"


def test_get_mode_for_boundary_execution_key_falls_back_to_template():
    db = get_db()
    try:
        _insert_project(db, "p-tmpl")
        set_modes(db, "p-tmpl", {"3.x": "clear"})

        result = get_mode_for_boundary(db, "p-tmpl", "3.7")
    finally:
        db.close()

    assert result == "clear"


def test_get_mode_for_boundary_exact_wins_over_template():
    db = get_db()
    try:
        _insert_project(db, "p-exact-win")
        set_modes(db, "p-exact-win", {"3.2": "clear", "3.x": "compact"})

        result = get_mode_for_boundary(db, "p-exact-win", "3.2")
    finally:
        db.close()

    assert result == "clear"


def test_get_mode_for_boundary_execution_key_with_no_rows_returns_none():
    db = get_db()
    try:
        _insert_project(db, "p-no-rows")

        result = get_mode_for_boundary(db, "p-no-rows", "3.5")
    finally:
        db.close()

    assert result == "none"


def test_get_mode_for_boundary_non_3_key_with_no_row_returns_none():
    db = get_db()
    try:
        _insert_project(db, "p-non3")

        result = get_mode_for_boundary(db, "p-non3", "4")
    finally:
        db.close()

    assert result == "none"


def test_get_mode_for_boundary_non_3_key_does_not_use_template_fallback():
    """A '4' boundary must not accidentally use the '3.x' template row."""
    db = get_db()
    try:
        _insert_project(db, "p-non3-tmpl")
        set_modes(db, "p-non3-tmpl", {"3.x": "clear"})

        result = get_mode_for_boundary(db, "p-non3-tmpl", "4")
    finally:
        db.close()

    assert result == "none"


# ── set_modes validation ──────────────────────────────────────────────────────


def test_set_modes_empty_boundary_key_raises_invalid_key():
    db = get_db()
    try:
        _insert_project(db, "p-bad-key")

        with pytest.raises(AdvanceModeServiceError) as exc_info:
            set_modes(db, "p-bad-key", {"": "compact"})
    finally:
        db.close()

    assert exc_info.value.code == "invalid_key"


def test_set_modes_whitespace_boundary_key_raises_invalid_key():
    db = get_db()
    try:
        _insert_project(db, "p-ws-key")

        with pytest.raises(AdvanceModeServiceError) as exc_info:
            set_modes(db, "p-ws-key", {"   ": "compact"})
    finally:
        db.close()

    assert exc_info.value.code == "invalid_key"


def test_set_modes_invalid_mode_raises_invalid_mode():
    db = get_db()
    try:
        _insert_project(db, "p-bad-mode")

        with pytest.raises(AdvanceModeServiceError) as exc_info:
            set_modes(db, "p-bad-mode", {"2": "flash"})
    finally:
        db.close()

    assert exc_info.value.code == "invalid_mode"


def test_set_modes_validation_failure_writes_no_rows():
    """When one entry in the batch is invalid, no rows must be persisted."""
    db = get_db()
    try:
        _insert_project(db, "p-atomic")
        set_modes(db, "p-atomic", {"1": "none"})

        with pytest.raises(AdvanceModeServiceError):
            set_modes(db, "p-atomic", {"2": "compact", "bad-key-empty": ""})

        rows = list_modes(db, "p-atomic")
    finally:
        db.close()

    assert rows == {"1": "none"}


def test_set_modes_validation_failure_all_or_nothing_on_fresh_project():
    """A completely invalid batch leaves the project with no rows at all."""
    db = get_db()
    try:
        _insert_project(db, "p-fresh-atomic")

        with pytest.raises(AdvanceModeServiceError):
            set_modes(db, "p-fresh-atomic", {"valid-key": "bad-mode"})

        rows = list_modes(db, "p-fresh-atomic")
    finally:
        db.close()

    assert rows == {}


# ── seed_default_modes ────────────────────────────────────────────────────────


def test_seed_default_modes_inserts_all_6_rows():
    db = get_db()
    try:
        _insert_project(db, "p-seed")
        seed_default_modes(db, "p-seed")

        rows = list_modes(db, "p-seed")
    finally:
        db.close()

    assert rows == DEFAULT_MODES


def test_default_mode_for_boundary_5_is_clear():
    """Boundary '5' (Reflection / Manual implementation) defaults to a fresh session
    so the 4.2 → 5.1 transition starts the reflection phase with no leftover context."""

    assert DEFAULT_MODES["5"] == "clear"


def test_seed_default_modes_is_idempotent():
    db = get_db()
    try:
        _insert_project(db, "p-idem")
        seed_default_modes(db, "p-idem")
        seed_default_modes(db, "p-idem")

        rows = list_modes(db, "p-idem")
    finally:
        db.close()

    assert rows == DEFAULT_MODES


def test_seed_default_modes_does_not_overwrite_user_values():
    db = get_db()
    try:
        _insert_project(db, "p-preserve")
        set_modes(db, "p-preserve", {"2": "clear"})
        seed_default_modes(db, "p-preserve")

        rows = list_modes(db, "p-preserve")
    finally:
        db.close()

    assert rows["2"] == "clear"


# ── project creation route seeds defaults ─────────────────────────────────────


def test_register_project_route_seeds_default_modes(client, git_repo):
    response = client.post("/api/projects", json={"path": git_repo, "name": "Seeded Project"})
    assert response.status_code == 201
    project_id = response.get_json()["id"]

    db = get_db()
    try:
        rows = list_modes(db, project_id)
    finally:
        db.close()

    assert rows == DEFAULT_MODES
