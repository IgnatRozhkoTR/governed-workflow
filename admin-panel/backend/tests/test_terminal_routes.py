"""Tests for terminal REST routes (paste-image upload)."""
import base64
import io
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.terminal as terminal_module

# 1x1 transparent PNG, decoded per-test so uploads carry real image bytes.
_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
    "2mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

PASTE_URL = "/api/ws/test-project/feature/test/terminal/paste-image"


def _png_bytes():
    return base64.b64decode(_PNG_BASE64)


_REAL_SUBPROCESS_RUN = subprocess.run


def _fake_run(returncodes):
    """Build a subprocess.run stand-in keyed by command prefix.

    ``returncodes`` maps a command-name string ("osascript", "has-session",
    "send-keys") to the returncode subprocess.run should report. Commands
    outside that vocabulary (e.g. the ``git`` calls made by test fixtures)
    are passed through to the real subprocess.run so patching the shared
    stdlib module doesn't break unrelated fixtures; a listed-but-unmocked
    key still raises so an untested paste-image code path can never fall
    through to a real tmux/osascript invocation.
    """

    def run(cmd, *args, **kwargs):
        if cmd[0] == "osascript":
            key = "osascript"
        elif cmd[:2] == ["tmux", "has-session"]:
            key = "has-session"
        elif cmd[:2] == ["tmux", "send-keys"] and "C-v" in cmd:
            key = "send-keys"
        else:
            return _REAL_SUBPROCESS_RUN(cmd, *args, **kwargs)
        if key not in returncodes:
            raise AssertionError(f"Unmocked subprocess call for {key!r}: {cmd}")
        return SimpleNamespace(returncode=returncodes[key], args=cmd)

    return run


@pytest.fixture(autouse=True)
def no_real_subprocess(monkeypatch):
    """Default every test in this module to a session-less, native-write-failing
    world so no test can accidentally spawn real tmux/osascript processes or
    touch the developer's actual clipboard.
    """
    monkeypatch.setattr(
        terminal_module.subprocess, "run",
        _fake_run({"osascript": 1, "has-session": 1}),
    )


def test_paste_image_saves_png_and_returns_path(client, workspace):
    png = _png_bytes()
    data = {"image": (io.BytesIO(png), "screenshot.png", "image/png")}

    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["mode"] == "path"

    saved = Path(r.json["path"])
    expected_dir = Path(workspace["working_dir"]) / ".claude" / "state" / "pasted-images"
    assert saved.parent == expected_dir
    assert saved.suffix == ".png"
    assert saved.exists()
    assert saved.read_bytes() == png


def test_paste_image_rejects_non_image(client, workspace):
    data = {"image": (io.BytesIO(b"not an image"), "notes.txt", "text/plain")}

    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 400
    assert "not an image" in r.json["error"].lower()


def test_paste_image_missing_file_returns_400(client, workspace):
    r = client.post(PASTE_URL, data={}, content_type="multipart/form-data")

    assert r.status_code == 400
    assert r.json["error"] == "No image provided"


def test_paste_image_unknown_workspace_returns_404(client, workspace):
    png = _png_bytes()
    data = {"image": (io.BytesIO(png), "screenshot.png", "image/png")}

    r = client.post(
        "/api/ws/test-project/feature/does-not-exist/terminal/paste-image",
        data=data,
        content_type="multipart/form-data",
    )

    assert r.status_code == 404
    assert r.json["error"] == "Workspace not found"


def _recording_fake_run(returncodes):
    calls = []
    inner = _fake_run(returncodes)

    def run(cmd, *args, **kwargs):
        calls.append(cmd)
        return inner(cmd, *args, **kwargs)

    return run, calls


def test_paste_image_non_darwin_non_linux_falls_back_to_path(client, workspace, monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "win32")
    run, calls = _recording_fake_run({})
    monkeypatch.setattr(terminal_module.subprocess, "run", run)

    data = {"image": (io.BytesIO(_png_bytes()), "screenshot.png", "image/png")}
    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert r.json["mode"] == "path"
    assert calls == []


def test_paste_image_macos_clipboard_success_with_session_uses_clipboard_mode(client, workspace, monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")
    run, calls = _recording_fake_run({"osascript": 0, "has-session": 0, "send-keys": 0})
    monkeypatch.setattr(terminal_module.subprocess, "run", run)

    data = {"image": (io.BytesIO(_png_bytes()), "screenshot.png", "image/png")}
    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert r.json["mode"] == "clipboard"

    saved_path = r.json["path"]
    osascript_calls = [c for c in calls if c[0] == "osascript"]
    assert len(osascript_calls) == 1
    assert saved_path in osascript_calls[0][2]

    send_keys_calls = [c for c in calls if c[:2] == ["tmux", "send-keys"]]
    assert len(send_keys_calls) == 1
    assert "C-v" in send_keys_calls[0]


def test_paste_image_macos_osascript_nonzero_returncode_falls_back_to_path(client, workspace, monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")
    run, calls = _recording_fake_run({"osascript": 1})
    monkeypatch.setattr(terminal_module.subprocess, "run", run)

    data = {"image": (io.BytesIO(_png_bytes()), "screenshot.png", "image/png")}
    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert r.json["mode"] == "path"
    assert not any(c[:2] == ["tmux", "send-keys"] for c in calls)


def test_paste_image_macos_osascript_raises_falls_back_to_path(client, workspace, monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")

    def raising_run(cmd, *args, **kwargs):
        if cmd[0] == "osascript":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)
        return _REAL_SUBPROCESS_RUN(cmd, *args, **kwargs)

    monkeypatch.setattr(terminal_module.subprocess, "run", raising_run)

    data = {"image": (io.BytesIO(_png_bytes()), "screenshot.png", "image/png")}
    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["mode"] == "path"


def test_paste_image_clipboard_success_but_no_session_falls_back_to_path(client, workspace, monkeypatch):
    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")
    run, calls = _recording_fake_run({"osascript": 0, "has-session": 1})
    monkeypatch.setattr(terminal_module.subprocess, "run", run)

    data = {"image": (io.BytesIO(_png_bytes()), "screenshot.png", "image/png")}
    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert r.json["mode"] == "path"
    assert not any(c[:2] == ["tmux", "send-keys"] for c in calls)


def test_paste_image_refuses_native_injection_when_working_dir_has_unsafe_chars(
    client, project, monkeypatch, tmp_path
):
    """A working_dir with a space and a double quote must never be interpolated
    unescaped into the AppleScript string handed to osascript.
    """
    unsafe_dir = tmp_path / 'weird "dir" name'
    unsafe_dir.mkdir()

    from core.db import get_db
    from datetime import datetime
    db = get_db()
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?)",
        (project["id"], "feature/unsafe", "feature-unsafe", str(unsafe_dir),
         now, '{"description":"","systemDiagram":"","execution":[]}', "develop"),
    )
    db.commit()
    db.close()

    monkeypatch.setattr(terminal_module.sys, "platform", "darwin")
    run, calls = _recording_fake_run({"osascript": 0, "has-session": 0, "send-keys": 0})
    monkeypatch.setattr(terminal_module.subprocess, "run", run)

    data = {"image": (io.BytesIO(_png_bytes()), "screenshot.png", "image/png")}
    r = client.post(
        "/api/ws/test-project/feature/unsafe/terminal/paste-image",
        data=data,
        content_type="multipart/form-data",
    )

    assert r.status_code == 200
    assert r.json["mode"] == "path"
    assert not any(c[0] == "osascript" for c in calls)
