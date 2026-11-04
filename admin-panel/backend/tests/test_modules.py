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


# --- resolve_enabled_module_overrides ---


@pytest.fixture
def db(clean_db):
    from core.db import get_db
    conn = get_db()
    yield conn
    conn.close()


def _enable_module(db, module_id: str, enabled_at: str) -> None:
    db.execute(
        "INSERT INTO modules_enabled (module_id, enabled_at) VALUES (?, ?)",
        (module_id, enabled_at),
    )
    db.commit()


def _make_module(root: Path, module_id: str, override_subpath: str | None = None,
                  override_files: dict[str, str] | None = None) -> Path:
    """Create a minimal module directory (SKILL.md required) with optional overrides."""
    mod_dir = root / module_id
    mod_dir.mkdir(parents=True)
    (mod_dir / "SKILL.md").write_text(f"---\nname: {module_id}\n---\n")
    if override_subpath is not None:
        override_dir = mod_dir / "override" / override_subpath
        override_dir.mkdir(parents=True)
        for rel, content in (override_files or {}).items():
            target = override_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    return mod_dir


def test_resolve_enabled_module_overrides_empty_when_no_modules_enabled(db, tmp_path):
    from services.modules_discovery import resolve_enabled_module_overrides
    _make_module(tmp_path, "mod-a", "agents", {"agent.md": "a"})
    result = resolve_enabled_module_overrides(db, "agents", [tmp_path])
    assert result == {}


def test_resolve_enabled_module_overrides_missing_override_dir_is_normal(db, tmp_path):
    from services.modules_discovery import resolve_enabled_module_overrides
    _make_module(tmp_path, "mod-a")  # no override/ directory at all
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")
    result = resolve_enabled_module_overrides(db, "agents", [tmp_path])
    assert result == {}


def test_resolve_enabled_module_overrides_single_module(db, tmp_path):
    from services.modules_discovery import resolve_enabled_module_overrides
    _make_module(tmp_path, "mod-a", "agents", {"agent.md": "from mod-a"})
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")
    result = resolve_enabled_module_overrides(db, "agents", [tmp_path])
    assert set(result.keys()) == {"agent.md"}
    assert result["agent.md"].read_text() == "from mod-a"


def test_resolve_enabled_module_overrides_disabled_module_ignored(db, tmp_path):
    from services.modules_discovery import resolve_enabled_module_overrides
    _make_module(tmp_path, "mod-a", "agents", {"agent.md": "a"})
    _make_module(tmp_path, "mod-b", "agents", {"agent.md": "b"})
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")
    # mod-b is never enabled
    result = resolve_enabled_module_overrides(db, "agents", [tmp_path])
    assert result["agent.md"].read_text() == "a"


def test_resolve_enabled_module_overrides_later_enabled_wins_on_collision(db, tmp_path):
    """A later enabled_at wins regardless of module_id alphabetical order."""
    from services.modules_discovery import resolve_enabled_module_overrides
    _make_module(tmp_path, "zzz-first", "agents", {"agent.md": "from zzz-first"})
    _make_module(tmp_path, "aaa-second", "agents", {"agent.md": "from aaa-second"})
    _enable_module(db, "zzz-first", "2024-01-01T00:00:00")
    _enable_module(db, "aaa-second", "2024-01-02T00:00:00")

    result = resolve_enabled_module_overrides(db, "agents", [tmp_path])

    assert result["agent.md"].read_text() == "from aaa-second"


def test_resolve_enabled_module_overrides_tie_break_by_module_id(db, tmp_path):
    """When enabled_at ties, the alphabetically later module_id wins."""
    from services.modules_discovery import resolve_enabled_module_overrides
    _make_module(tmp_path, "mod-a", "agents", {"agent.md": "from mod-a"})
    _make_module(tmp_path, "mod-b", "agents", {"agent.md": "from mod-b"})
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")
    _enable_module(db, "mod-b", "2024-01-01T00:00:00")

    result = resolve_enabled_module_overrides(db, "agents", [tmp_path])

    assert result["agent.md"].read_text() == "from mod-b"


def test_resolve_enabled_module_overrides_modules_local_shadows_tracked(db, tmp_path):
    """A modules-local copy of an enabled module shadows the tracked one for overrides too."""
    from services.modules_discovery import resolve_enabled_module_overrides
    tracked = tmp_path / "tracked"
    local = tmp_path / "local"
    tracked.mkdir()
    local.mkdir()
    # Tracked copy has SKILL.md but no override/ at all.
    _make_module(tracked, "mod-x")
    # Local copy has SKILL.md and an override/agents/ file.
    _make_module(local, "mod-x", "agents", {"agent.md": "from local"})
    _enable_module(db, "mod-x", "2024-01-01T00:00:00")

    result = resolve_enabled_module_overrides(db, "agents", [tracked, local])

    assert result["agent.md"].read_text() == "from local"


def test_resolve_enabled_module_overrides_scans_recursively(db, tmp_path):
    from services.modules_discovery import resolve_enabled_module_overrides
    _make_module(
        tmp_path, "mod-a", "rules",
        {"nested/deep.md": "deep content", "top.md": "top content"},
    )
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")

    result = resolve_enabled_module_overrides(db, "rules", [tmp_path])

    assert set(result.keys()) == {"nested/deep.md", "top.md"}
    assert result["nested/deep.md"].read_text() == "deep content"


def test_resolve_enabled_module_overrides_scoped_by_subpath(db, tmp_path):
    """Files under a different override subpath are not returned."""
    from services.modules_discovery import resolve_enabled_module_overrides
    _make_module(tmp_path, "mod-a", "agents", {"agent.md": "a"})
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")

    assert resolve_enabled_module_overrides(db, "rules", [tmp_path]) == {}
    assert resolve_enabled_module_overrides(db, "agents", [tmp_path]) != {}
