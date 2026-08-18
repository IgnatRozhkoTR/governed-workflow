"""Tests for claude/tools/kotlin-lsp-launcher.py, the direct-JVM kotlin-lsp launcher.

The native cask launcher (bin/intellij-server) freezes at dyld load on some
machines, so the admin panel spawns this script instead, which invokes the
bundled JBR java directly using the arguments product-info.json describes.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.paths import DEFAULT_TOOLS_DIR

LAUNCHER_PATH = DEFAULT_TOOLS_DIR / "kotlin-lsp-launcher.py"


def _load_launcher_module():
    spec = importlib.util.spec_from_file_location("kotlin_lsp_launcher", str(LAUNCHER_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def launcher():
    return _load_launcher_module()


@pytest.fixture
def fake_dist(tmp_path):
    """A minimal kotlin-lsp distribution: product-info.json + vmoptions + a fake java binary."""
    dist_dir = tmp_path / "kotlin-server-262.9593.0"
    (dist_dir / "bin").mkdir(parents=True)
    (dist_dir / "jbr" / "Contents" / "Home" / "bin").mkdir(parents=True)
    java_bin = dist_dir / "jbr" / "Contents" / "Home" / "bin" / "java"
    java_bin.write_text("#!/bin/sh\necho fake java\n")
    java_bin.chmod(0o755)

    (dist_dir / "bin" / "intellij-server.vmoptions").write_text(
        "-Xmx2048m\n# a comment\n\n-Dfile.encoding=UTF-8\n"
    )

    product_info = {
        "launch": [
            {
                "javaExecutablePath": "jbr/Contents/Home/bin/java",
                "vmOptionsFilePath": "bin/intellij-server.vmoptions",
                "bootClassPathJarNames": ["platform-loader.jar", "util.jar"],
                "additionalJvmArguments": [
                    "-Xbootclasspath/a:$APP_PACKAGE/Contents/lib/nio-fs.jar",
                    "-Djna.boot.library.path=$APP_PACKAGE/Contents/lib/jna/aarch64",
                    "-Didea.platform.prefix=IntelliJServer",
                ],
                "mainClass": "com.intellij.ls.server.MainImpl",
            }
        ]
    }
    (dist_dir / "product-info.json").write_text(json.dumps(product_info))
    return dist_dir


def test_build_command_rewrites_app_package_prefixes(launcher, fake_dist):
    command = launcher.build_command(str(fake_dist), [])

    assert command[0] == str(fake_dist / "jbr" / "Contents" / "Home" / "bin" / "java")
    assert f"-Xbootclasspath/a:{fake_dist}/lib/nio-fs.jar" in command
    assert f"-Djna.boot.library.path={fake_dist}/lib/jna/aarch64" in command
    assert "-Didea.platform.prefix=IntelliJServer" in command


def test_build_command_includes_vmoptions_and_forces_xshare_off(launcher, fake_dist):
    command = launcher.build_command(str(fake_dist), [])

    assert "-Xmx2048m" in command
    assert "-Dfile.encoding=UTF-8" in command
    assert "-Xshare:off" in command


def test_build_command_joins_classpath_from_boot_classpath_jar_names(launcher, fake_dist):
    command = launcher.build_command(str(fake_dist), [])

    cp_index = command.index("-cp")
    classpath = command[cp_index + 1]
    assert classpath == f"{fake_dist}/lib/platform-loader.jar:{fake_dist}/lib/util.jar"


def test_build_command_places_main_class_after_classpath(launcher, fake_dist):
    command = launcher.build_command(str(fake_dist), [])

    cp_index = command.index("-cp")
    assert command[cp_index + 2] == "com.intellij.ls.server.MainImpl"


def test_build_command_splits_dash_d_args_before_cp_and_stdio_after_main_class(launcher, fake_dist):
    extra_argv = ["-Didea.config.path=/cache/config", "-Didea.system.path=/cache/system", "--stdio"]

    command = launcher.build_command(str(fake_dist), extra_argv)

    cp_index = command.index("-cp")
    main_class_index = cp_index + 2
    assert "-Didea.config.path=/cache/config" in command[:cp_index]
    assert "-Didea.system.path=/cache/system" in command[:cp_index]
    assert command[main_class_index + 1:] == ["--stdio"]


def test_resolve_dist_dir_honors_kotlin_lsp_home_env_var(launcher, fake_dist, monkeypatch):
    monkeypatch.setenv("KOTLIN_LSP_HOME", str(fake_dist))

    assert launcher._resolve_dist_dir() == str(fake_dist)


def test_resolve_dist_dir_returns_none_when_no_env_var_and_no_cask_glob_match(launcher, monkeypatch):
    monkeypatch.delenv("KOTLIN_LSP_HOME", raising=False)
    monkeypatch.setattr(launcher.glob, "glob", lambda pattern: [])

    assert launcher._resolve_dist_dir() is None


def test_resolve_dist_dir_picks_newest_version_from_glob_matches(launcher, monkeypatch):
    monkeypatch.delenv("KOTLIN_LSP_HOME", raising=False)
    matches = [
        "/opt/homebrew/Caskroom/kotlin-lsp/260.1.0/kotlin-server-260.1.0/",
        "/opt/homebrew/Caskroom/kotlin-lsp/262.9593.0/kotlin-server-262.9593.0/",
        "/opt/homebrew/Caskroom/kotlin-lsp/261.5.2/kotlin-server-261.5.2/",
    ]
    monkeypatch.setattr(launcher.glob, "glob", lambda pattern: matches)

    assert launcher._resolve_dist_dir() == "/opt/homebrew/Caskroom/kotlin-lsp/262.9593.0/kotlin-server-262.9593.0"


def test_cli_print_cmd_outputs_constructed_argv_as_json(fake_dist):
    result = subprocess.run(
        [sys.executable, str(LAUNCHER_PATH), "--print-cmd", "-Didea.config.path=/cache/config", "--stdio"],
        env={"KOTLIN_LSP_HOME": str(fake_dist), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    command = json.loads(result.stdout)
    assert command[0] == str(fake_dist / "jbr" / "Contents" / "Home" / "bin" / "java")
    assert command[-1] == "--stdio"
    assert "-Didea.config.path=/cache/config" in command


def test_main_print_cmd_fails_loudly_when_no_dist_found(launcher, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "_resolve_dist_dir", lambda: None)
    monkeypatch.setattr(sys, "argv", ["kotlin-lsp-launcher.py", "--print-cmd", "--stdio"])

    with pytest.raises(SystemExit) as exc_info:
        launcher.main()

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "kotlin-lsp-launcher" in captured.err


def test_main_execs_plain_kotlin_lsp_when_no_dist_found(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "_resolve_dist_dir", lambda: None)
    monkeypatch.setattr(sys, "argv", ["kotlin-lsp-launcher.py", "--stdio"])
    captured = {}

    def fake_execvp(command, argv):
        captured["command"] = command
        captured["argv"] = argv

    monkeypatch.setattr(launcher.os, "execvp", fake_execvp)

    launcher.main()

    assert captured == {"command": "kotlin-lsp", "argv": ["kotlin-lsp", "--stdio"]}
