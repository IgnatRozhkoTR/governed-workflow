import fcntl
import os
import pty
import select
import signal
import struct
import termios
import tty

import pytest

from core import terminal
from core.terminal import parse_resize_frame


def test_parse_resize_frame_returns_size_for_exact_control_frame():
    assert parse_resize_frame('{"resize": [120, 40]}') == (120, 40)


@pytest.mark.parametrize('text', [
    '{"resize": [80, 24], "note": "user text"}',
    '{"name": "value"}',
    '{not json',
    '[1, 2]',
])
def test_parse_resize_frame_returns_none_for_json_like_user_text(text):
    assert parse_resize_frame(text) is None


@pytest.mark.parametrize('text', [
    '{"resize": 5}',
    '{"resize": [80]}',
    '{"resize": [80, 24, 1]}',
    '{"resize": ["80", 24]}',
    '{"resize": [0, 24]}',
    '{"resize": [80, -1]}',
    '{"resize": [80, 100000]}',
    '{"resize": [true, 24]}',
    '{"resize": [80.5, 24]}',
    '{"resize": null}',
])
def test_parse_resize_frame_returns_none_for_malformed_resize(text):
    assert parse_resize_frame(text) is None


def test_parse_resize_frame_returns_none_for_ordinary_text():
    assert parse_resize_frame('ls -la\r') is None


class _ScriptedWebSocket:
    """Feeds frames, then snapshots the pty slave before the bridge closes the master."""

    def __init__(self, slave_fd, frames):
        self._slave_fd = slave_fd
        self._frames = list(frames)
        self.forwarded = ''
        self.window_size = None

    def receive(self):
        if self._frames:
            return self._frames.pop(0)
        self.forwarded = _read_forwarded(self._slave_fd)
        self.window_size = _window_size(self._slave_fd)
        return None

    def send(self, data):
        pass


@pytest.fixture
def pty_pair(monkeypatch):
    master_fd, slave_fd = pty.openpty()
    tty.setraw(slave_fd)
    signalled = []
    monkeypatch.setattr(terminal, 'spawn_pty_process', lambda argv: (os.getpid(), master_fd))
    monkeypatch.setattr(terminal.os, 'kill', lambda pid, sig: signalled.append(sig))
    yield slave_fd, signalled
    os.close(slave_fd)


def _read_forwarded(slave_fd):
    chunks = []
    while select.select([slave_fd], [], [], 0.2)[0]:
        chunk = os.read(slave_fd, 4096)
        if not chunk:
            break
        chunks.append(chunk)
    return b''.join(chunks).decode()


def _window_size(slave_fd):
    rows, cols, _, _ = struct.unpack('HHHH', fcntl.ioctl(slave_fd, termios.TIOCGWINSZ, b'\0' * 8))
    return cols, rows


def _run_bridge(slave_fd, frames):
    ws = _ScriptedWebSocket(slave_fd, frames)
    terminal.run_pty_websocket(ws, 'unused')
    return ws


def test_run_pty_websocket_resizes_pty_for_valid_resize_frame(pty_pair):
    slave_fd, signalled = pty_pair

    ws = _run_bridge(slave_fd, ['{"resize": [132, 43]}'])

    assert ws.window_size == (132, 43)
    assert signalled == [signal.SIGWINCH]
    assert ws.forwarded == ''


def test_run_pty_websocket_forwards_json_like_user_text(pty_pair):
    slave_fd, signalled = pty_pair
    user_text = '{"resize": [80, 24], "msg": "hi"}'

    ws = _run_bridge(slave_fd, [user_text])

    assert ws.forwarded == user_text
    assert signalled == []


def test_run_pty_websocket_forwards_malformed_resize_and_keeps_session_open(pty_pair):
    slave_fd, signalled = pty_pair

    ws = _run_bridge(slave_fd, ['{"resize":5}', 'echo ok\r'])

    assert ws.forwarded == '{"resize":5}echo ok\r'
    assert signalled == []


def test_run_pty_websocket_forwards_ordinary_text(pty_pair):
    slave_fd, _ = pty_pair

    ws = _run_bridge(slave_fd, ['ls -la\r'])

    assert ws.forwarded == 'ls -la\r'
