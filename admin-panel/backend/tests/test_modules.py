"""Tests for modules discovery and enabled-state endpoints."""
from pathlib import Path

import pytest


# --- iter_module_dirs unit tests ---

def test_iter_module_dirs_empty_roots_returns_empty():
    from services.modules_discovery import iter_module_dirs
    assert iter_module_dirs([]) == []


def test_iter_module_dirs_single_root_filters_without_skill(tmp_path):
    from services.modules_discovery import iter_module_dirs
    (tmp_path / "valid").mkdir()
    (tmp_path / "valid" / "SKILL.md").write_text("---\nname: Valid\n---")
    (tmp_path / "invalid").mkdir()
    result = iter_module_dirs([tmp_path])
    assert result == [tmp_path / "valid"]


def test_iter_module_dirs_multi_root_merges(tmp_path):
    from services.modules_discovery import iter_module_dirs
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "alpha").mkdir()
    (root_a / "alpha" / "SKILL.md").write_text("")
    (root_b / "beta").mkdir()
    (root_b / "beta" / "SKILL.md").write_text("")
    result = iter_module_dirs([root_a, root_b])
    assert [p.name for p in result] == ["alpha", "beta"]


def test_iter_module_dirs_local_shadows_tracked(tmp_path):
    from services.modules_discovery import iter_module_dirs
    tracked = tmp_path / "tracked"
    local = tmp_path / "local"
    tracked.mkdir()
    local.mkdir()
    (tracked / "mymod").mkdir()
    (tracked / "mymod" / "SKILL.md").write_text("")
    (local / "mymod").mkdir()
    (local / "mymod" / "SKILL.md").write_text("")
    result = iter_module_dirs([tracked, local])
    assert result == [local / "mymod"]


def test_iter_module_dirs_nonexistent_root_skipped(tmp_path):
    from services.modules_discovery import iter_module_dirs
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "mod").mkdir()
    (existing / "mod" / "SKILL.md").write_text("")
    result = iter_module_dirs([existing, tmp_path / "ghost"])
    assert result == [existing / "mod"]


# --- route test ---

def test_list_modules_route_reads_both_roots(client, tmp_path, monkeypatch):
    tracked = tmp_path / "tracked"
    local = tmp_path / "local"
    tracked.mkdir()
    local.mkdir()
    (tracked / "mod-a").mkdir()
    (tracked / "mod-a" / "SKILL.md").write_text("---\nname: Mod A\n---")
    (local / "mod-b").mkdir()
    (local / "mod-b" / "SKILL.md").write_text("---\nname: Mod B\n---")

    import routes.modules as mod_routes
    monkeypatch.setattr(mod_routes, "DEFAULT_MODULES_DIR", tracked)
    monkeypatch.setattr(mod_routes, "DEFAULT_MODULES_LOCAL_DIR", local)

    response = client.get("/api/modules")
    assert response.status_code == 200
    ids = [m["id"] for m in response.get_json()["modules"]]
    assert "mod-a" in ids
    assert "mod-b" in ids


# --- original tests ---

def test_list_modules(client):
    """GET /api/modules returns list (may be empty or contain telegram)."""
    response = client.get("/api/modules")
    assert response.status_code == 200
    data = response.get_json()
    assert "modules" in data
    assert isinstance(data["modules"], list)


def test_list_modules_structure(client):
    """Each module has id, name, description, path, has_skill fields."""
    response = client.get("/api/modules")
    assert response.status_code == 200
    data = response.get_json()
    for module in data["modules"]:
        assert "id" in module
        assert "name" in module
        assert "description" in module
        assert "path" in module
        assert "has_skill" in module
        assert module["has_skill"] is True


def test_list_modules_contains_telegram(client):
    """GET /api/modules includes telegram module from the repo modules directory."""
    response = client.get("/api/modules")
    assert response.status_code == 200
    data = response.get_json()
    ids = [m["id"] for m in data["modules"]]
    assert "telegram" in ids


def test_get_enabled_modules_empty(client):
    """GET /api/modules/enabled returns empty list initially."""
    response = client.get("/api/modules/enabled")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"modules": []}


def test_set_enabled_modules(client):
    """POST /api/modules/enabled saves module IDs."""
    response = client.post("/api/modules/enabled", json={"modules": ["telegram"]})
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"status": "saved"}


def test_set_enabled_modules_replaces(client):
    """POST /api/modules/enabled replaces previous list entirely."""
    client.post("/api/modules/enabled", json={"modules": ["telegram", "other"]})
    client.post("/api/modules/enabled", json={"modules": ["telegram"]})
    response = client.get("/api/modules/enabled")
    assert response.status_code == 200
    data = response.get_json()
    assert data["modules"] == ["telegram"]


def test_set_enabled_modules_empty(client):
    """POST /api/modules/enabled with empty list clears all."""
    client.post("/api/modules/enabled", json={"modules": ["telegram"]})
    client.post("/api/modules/enabled", json={"modules": []})
    response = client.get("/api/modules/enabled")
    assert response.status_code == 200
    data = response.get_json()
    assert data["modules"] == []


def test_get_enabled_after_set(client):
    """GET returns what was previously POSTed."""
    client.post("/api/modules/enabled", json={"modules": ["telegram", "other-module"]})
    response = client.get("/api/modules/enabled")
    assert response.status_code == 200
    data = response.get_json()
    assert sorted(data["modules"]) == sorted(["telegram", "other-module"])
