"""Tests for the persistent LSP cache dir placeholder substitution and cleanup."""
from services import lsp_service


def test_substitute_leaves_args_without_placeholder_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    args = ["--stdio"]
    result = lsp_service._substitute_lsp_cache_dir(args, "proj", 5)

    assert result == ["--stdio"]
    assert not (tmp_path / "lsp-cache").exists()


def test_substitute_replaces_placeholder_and_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    args = ["-Didea.config.path={lsp_cache_dir}/config", "-Didea.system.path={lsp_cache_dir}/system", "--stdio"]
    result = lsp_service._substitute_lsp_cache_dir(args, "proj", 5)

    cache_dir = lsp_service.lsp_cache_dir("proj", 5)
    assert result == [
        f"-Didea.config.path={cache_dir}/config",
        f"-Didea.system.path={cache_dir}/system",
        "--stdio",
    ]
    assert cache_dir.is_dir()


def test_substitute_creates_dir_only_once_for_multiple_placeholder_args(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    args = ["--a={lsp_cache_dir}/a", "--b={lsp_cache_dir}/b"]
    lsp_service._substitute_lsp_cache_dir(args, "proj", 5)

    cache_dir = lsp_service.lsp_cache_dir("proj", 5)
    assert cache_dir.parent.name == "proj"
    assert [p.name for p in cache_dir.parent.iterdir()] == [cache_dir.name]


def test_cache_key_sanitizes_unsafe_project_id_characters(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    cache_dir = lsp_service.lsp_cache_dir("weird/proj id!", 7)

    project_dir = cache_dir.parent
    assert project_dir.parent == tmp_path / "lsp-cache"
    assert "/" not in project_dir.name
    assert " " not in project_dir.name
    assert cache_dir.name == "7"


def test_cache_key_differs_per_profile_for_same_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    assert lsp_service.lsp_cache_dir("proj", 1) != lsp_service.lsp_cache_dir("proj", 2)


def test_remove_lsp_cache_dirs_does_not_touch_projects_with_shared_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    own_dir = lsp_service.lsp_cache_dir("proj-a", 1)
    own_dir.mkdir(parents=True)
    (own_dir / "config").mkdir()
    other_dir = lsp_service.lsp_cache_dir("proj-a-extra", 1)
    other_dir.mkdir(parents=True)

    lsp_service.remove_lsp_cache_dirs("proj-a")

    assert not own_dir.exists()
    assert other_dir.exists()


def test_remove_lsp_cache_dirs_removes_every_profile_for_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    dir_profile_1 = lsp_service.lsp_cache_dir("proj-b", 1)
    dir_profile_2 = lsp_service.lsp_cache_dir("proj-b", 2)
    dir_profile_1.mkdir(parents=True)
    dir_profile_2.mkdir(parents=True)

    lsp_service.remove_lsp_cache_dirs("proj-b")

    assert not dir_profile_1.exists()
    assert not dir_profile_2.exists()


def test_remove_lsp_cache_dirs_is_a_noop_when_cache_root_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    lsp_service.remove_lsp_cache_dirs("nonexistent-project")


def test_remove_lsp_cache_dirs_swallows_removal_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))
    own_dir = lsp_service.lsp_cache_dir("proj-c", 1)
    own_dir.mkdir(parents=True)

    def _boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(lsp_service.shutil, "rmtree", _boom)

    lsp_service.remove_lsp_cache_dirs("proj-c")
