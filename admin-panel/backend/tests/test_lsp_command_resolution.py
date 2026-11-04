"""Tests for the {tools_dir} placeholder substitution in profile lsp_command."""
import stat

from core import paths
from services import lsp_service


def test_resolve_leaves_command_without_placeholder_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    assert lsp_service._resolve_lsp_command("kotlin-lsp") == ["kotlin-lsp"]


def test_resolve_substitutes_tools_dir_placeholder(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))
    launcher = tmp_path / "kotlin-lsp-launcher.py"
    launcher.write_text("#!/usr/bin/env python3\n")
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)

    result = lsp_service._resolve_lsp_command("{tools_dir}/kotlin-lsp-launcher.py")

    assert result == [str(launcher)]


def test_resolve_prefixes_python3_when_launcher_is_not_executable(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))
    launcher = tmp_path / "kotlin-lsp-launcher.py"
    launcher.write_text("#!/usr/bin/env python3\n")
    launcher.chmod(launcher.stat().st_mode & ~stat.S_IEXEC & ~stat.S_IXGRP & ~stat.S_IXOTH)

    result = lsp_service._resolve_lsp_command("{tools_dir}/kotlin-lsp-launcher.py")

    assert result == ["python3", str(launcher)]


def test_resolve_prefixes_python3_when_launcher_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    result = lsp_service._resolve_lsp_command("{tools_dir}/kotlin-lsp-launcher.py")

    assert result == ["python3", str(tmp_path / "kotlin-lsp-launcher.py")]


def test_tools_dir_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNED_WORKFLOW_TOOLS_DIR", str(tmp_path))

    assert paths.tools_dir() == tmp_path


def test_tools_dir_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("GOVERNED_WORKFLOW_TOOLS_DIR", raising=False)

    assert paths.tools_dir() == paths.DEFAULT_TOOLS_DIR
