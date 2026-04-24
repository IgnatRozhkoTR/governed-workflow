"""Tests for the ``backend/app.py`` CLI helpers.

Covers the admin-token subcommand guard (refuse to overwrite without
``--force``) and the clipboard integration that runs after a successful
generation.
"""
import subprocess
import sys

import pytest

from core.db import get_db
from core.device_settings import (
    clear_admin_token,
    get_admin_token_hash,
    set_admin_token,
    generate_token,
)

from app import (
    _copy_to_clipboard,
    _run_auth_token_command,
)


@pytest.fixture(autouse=True)
def _clean_token():
    db = get_db()
    try:
        clear_admin_token(db)
        db.commit()
    finally:
        db.close()
    yield
    db = get_db()
    try:
        clear_admin_token(db)
        db.commit()
    finally:
        db.close()


def _current_hash() -> str | None:
    db = get_db()
    try:
        return get_admin_token_hash(db)
    finally:
        db.close()


def test_auth_token_generates_when_no_token_configured(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["app.py", "auth-token"])
    monkeypatch.setattr("app._copy_to_clipboard", lambda _text: True)

    exit_code = _run_auth_token_command()

    assert exit_code == 0
    assert _current_hash() is not None
    captured = capsys.readouterr()
    assert "Copied to system clipboard" in captured.out


def test_auth_token_refuses_to_overwrite_without_force(monkeypatch, capsys):
    db = get_db()
    try:
        existing = generate_token()
        set_admin_token(db, existing)
        db.commit()
        existing_hash = get_admin_token_hash(db)
    finally:
        db.close()

    monkeypatch.setattr(sys, "argv", ["app.py", "auth-token"])
    monkeypatch.setattr("app._copy_to_clipboard", lambda _text: False)

    exit_code = _run_auth_token_command()

    assert exit_code == 1
    assert _current_hash() == existing_hash

    captured = capsys.readouterr()
    assert "already configured" in captured.err
    assert "--force" in captured.err
    assert "auth-reset" in captured.err


def test_auth_token_overwrites_with_force(monkeypatch, capsys):
    db = get_db()
    try:
        existing = generate_token()
        set_admin_token(db, existing)
        db.commit()
        existing_hash = get_admin_token_hash(db)
    finally:
        db.close()

    monkeypatch.setattr(sys, "argv", ["app.py", "auth-token", "--force"])
    monkeypatch.setattr("app._copy_to_clipboard", lambda _text: True)

    exit_code = _run_auth_token_command()

    assert exit_code == 0
    new_hash = _current_hash()
    assert new_hash is not None
    assert new_hash != existing_hash


def test_auth_token_prints_fallback_when_clipboard_fails(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["app.py", "auth-token"])
    monkeypatch.setattr("app._copy_to_clipboard", lambda _text: False)

    exit_code = _run_auth_token_command()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Copy the token above" in captured.out
    assert "Copied to system clipboard" not in captured.out


def test_copy_to_clipboard_invokes_pbcopy_on_darwin(monkeypatch):
    calls: list[dict] = []

    class FakeCompleted:
        def __init__(self):
            self.returncode = 0

    def _fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return FakeCompleted()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    ok = _copy_to_clipboard("secret-token")

    assert ok is True
    assert len(calls) == 1
    assert calls[0]["cmd"] == ["pbcopy"]
    assert calls[0]["kwargs"]["input"] == "secret-token"
    assert calls[0]["kwargs"]["shell"] is False


def test_copy_to_clipboard_tries_linux_tools_in_order(monkeypatch):
    attempts: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        attempts.append(cmd)

        class Result:
            pass

            returncode = 1 if cmd == ["wl-copy"] else 0

        return Result()

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    ok = _copy_to_clipboard("hello")

    assert ok is True
    assert attempts[0] == ["wl-copy"]
    assert attempts[1] == ["xclip", "-selection", "clipboard"]


def test_copy_to_clipboard_returns_false_when_no_tool_found(monkeypatch):
    def _fake_run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert _copy_to_clipboard("hello") is False


def test_copy_to_clipboard_returns_false_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd9")

    assert _copy_to_clipboard("hello") is False


def test_copy_to_clipboard_uses_shell_for_windows_clip(monkeypatch):
    captured: dict = {}

    class Result:
        returncode = 0

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["shell"] = kwargs.get("shell")
        return Result()

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    ok = _copy_to_clipboard("token")

    assert ok is True
    assert captured["cmd"] == "clip"
    assert captured["shell"] is True
