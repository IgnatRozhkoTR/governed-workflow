"""Unit tests for terminal helper functions."""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import core.terminal as terminal_module
from core.terminal import (
    _strip_ansi,
    _is_claude_ready,
    build_claude_command,
    copy_image_to_host_clipboard,
    mark_new_session,
    parse_env_vars,
    send_paste_keystroke,
    write_launch_env_file,
)


REALISTIC_PANE = """claude --dangerously-skip-permissions
 ▐▛███▜▌   Claude Code v2.1.85
▝▜█████▛▘  Opus 4.6 (1M context)
  ▘▘ ▝▝    /Users/test

────────────────────────────────────────────────────────────────────
❯
────────────────────────────────────────────────────────────────────
"""

TRUST_PROMPT_PANE = """Do you trust the files in /Users/test/project?
Press Enter to confirm.
"""


def test_strip_ansi_plain_text():
    assert _strip_ansi("hello world") == "hello world"


def test_strip_ansi_removes_color_codes():
    colored = "\x1b[31mred text\x1b[0m"
    assert _strip_ansi(colored) == "red text"


def test_strip_ansi_removes_cursor_codes():
    with_cursor = "\x1b[2J\x1b[H visible"
    assert _strip_ansi(with_cursor) == "visible"


def test_is_claude_ready_empty():
    assert _is_claude_ready("") is False


def test_is_claude_ready_no_prompt():
    assert _is_claude_ready("some output without the prompt character") is False


def test_is_claude_ready_with_prompt():
    pane = (
        "────────────────────────────────────────────────────────────────────\n"
        "❯\n"
        "────────────────────────────────────────────────────────────────────\n"
    )
    assert _is_claude_ready(pane) is True


def test_is_claude_ready_prompt_without_border():
    assert _is_claude_ready("❯ some line without any border around it") is False


def test_is_claude_ready_realistic():
    assert _is_claude_ready(REALISTIC_PANE) is True


def test_is_claude_ready_trust_prompt():
    assert _is_claude_ready(TRUST_PROMPT_PANE) is False


def test_mark_new_session_writes_force_new_session_flag(tmp_path):
    mark_new_session(str(tmp_path))

    flag = tmp_path / ".claude" / "state" / "force-new-session"
    assert flag.exists()


def test_mark_new_session_creates_state_dir_when_missing(tmp_path):
    target = tmp_path / "fresh-workspace"
    target.mkdir()

    mark_new_session(str(target))

    assert (target / ".claude" / "state" / "force-new-session").exists()


def test_parse_env_vars_valid_lines():
    pairs = parse_env_vars("FOO=bar\nBAZ=qux")
    assert pairs == [("FOO", "bar"), ("BAZ", "qux")]


def test_parse_env_vars_skips_comments_and_blanks():
    text = "# a comment\n\nFOO=bar\n   \n# another\nBAZ=qux\n"
    assert parse_env_vars(text) == [("FOO", "bar"), ("BAZ", "qux")]


def test_parse_env_vars_skips_line_without_equals():
    assert parse_env_vars("FOO=bar\nNOEQUALS\nBAZ=qux") == [("FOO", "bar"), ("BAZ", "qux")]


def test_parse_env_vars_skips_invalid_keys():
    text = "1BAD=value\nhas space=value\nGOOD_KEY=ok\n_OK=yes"
    assert parse_env_vars(text) == [("GOOD_KEY", "ok"), ("_OK", "yes")]


def test_parse_env_vars_strips_whitespace_around_key_and_value():
    assert parse_env_vars("  FOO  =  bar  ") == [("FOO", "bar")]


def test_parse_env_vars_keeps_everything_after_first_equals():
    assert parse_env_vars("CONN=key=value=more") == [("CONN", "key=value=more")]


def test_parse_env_vars_empty_text():
    assert parse_env_vars("") == []
    assert parse_env_vars(None) == []


def test_write_launch_env_file_writes_export_lines(tmp_path):
    count = write_launch_env_file(str(tmp_path), "FOO=bar\nBAZ=qux")

    assert count == 2
    content = (tmp_path / ".claude" / "state" / "launch-env").read_text()
    assert content == "export FOO=bar\nexport BAZ=qux\n"


def test_write_launch_env_file_shlex_quotes_special_values(tmp_path):
    write_launch_env_file(str(tmp_path), "MSG=hello world\nQ=it's \"quoted\"")

    content = (tmp_path / ".claude" / "state" / "launch-env").read_text()
    assert "export MSG='hello world'" in content
    # The single quote in the value forces shlex to break and re-quote.
    assert "export Q=" in content
    assert "it" in content and "quoted" in content


def test_write_launch_env_file_empty_when_no_vars(tmp_path):
    count = write_launch_env_file(str(tmp_path), "# only a comment\n")

    assert count == 0
    assert (tmp_path / ".claude" / "state" / "launch-env").read_text() == ""


def test_write_launch_env_file_creates_state_dir_when_missing(tmp_path):
    target = tmp_path / "fresh-workspace"
    target.mkdir()

    write_launch_env_file(str(target), "FOO=bar")

    assert (target / ".claude" / "state" / "launch-env").exists()


def test_build_claude_command_sources_launch_env():
    ws = {"working_dir": "/tmp/some-workspace"}
    command = build_claude_command(ws)

    assert "if [ -f .claude/state/launch-env ]; then . .claude/state/launch-env; fi;" in command


def test_copy_image_to_host_clipboard_returns_false_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "win32")
    monkeypatch.setattr(
        terminal_module.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    assert copy_image_to_host_clipboard("/tmp/image.png") is False


def test_copy_image_to_host_clipboard_returns_false_on_linux(monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "linux")
    monkeypatch.setattr(
        terminal_module.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    assert copy_image_to_host_clipboard("/tmp/image.png") is False


def test_copy_image_to_host_clipboard_macos_success_invokes_osascript(monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(terminal_module.subprocess, "run", fake_run)

    assert copy_image_to_host_clipboard("/tmp/image.png") is True
    assert len(calls) == 1
    assert calls[0][0] == "osascript"
    assert "/tmp/image.png" in calls[0][2]
    assert "«class PNGf»" in calls[0][2]


def test_copy_image_to_host_clipboard_macos_nonzero_returncode_returns_false(monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        terminal_module.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1),
    )

    assert copy_image_to_host_clipboard("/tmp/image.png") is False


def test_copy_image_to_host_clipboard_macos_timeout_returns_false(monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")

    def raising_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd=["osascript"], timeout=10)

    monkeypatch.setattr(terminal_module.subprocess, "run", raising_run)

    assert copy_image_to_host_clipboard("/tmp/image.png") is False


def test_copy_image_to_host_clipboard_macos_refuses_path_with_double_quote(monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        terminal_module.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    assert copy_image_to_host_clipboard('/tmp/weird "quoted" dir/image.png') is False


def test_copy_image_to_host_clipboard_macos_refuses_path_with_backslash(monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        terminal_module.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    assert copy_image_to_host_clipboard("/tmp/weird\\dir/image.png") is False


def test_send_paste_keystroke_returns_false_when_session_missing(monkeypatch):
    monkeypatch.setattr(
        terminal_module.subprocess, "run",
        lambda cmd, **k: SimpleNamespace(returncode=1),
    )

    assert send_paste_keystroke("ws-missing") is False


def test_send_paste_keystroke_sends_ctrl_v_when_session_exists(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["tmux", "has-session"]:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(terminal_module.subprocess, "run", fake_run)

    assert send_paste_keystroke("ws-exists") is True
    send_keys_calls = [c for c in calls if c[:2] == ["tmux", "send-keys"]]
    assert len(send_keys_calls) == 1
    assert "C-v" in send_keys_calls[0]
