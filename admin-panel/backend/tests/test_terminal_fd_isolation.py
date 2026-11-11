"""The PTY spawn helper must not leak the server's inheritable fds to children."""
import os
import select
import socket

from core.terminal import spawn_pty_process


def _read_until_exit(master_fd):
    output = b""
    while select.select([master_fd], [], [], 5)[0]:
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
    return output.decode(errors="replace")


def test_spawn_pty_process_does_not_inherit_listening_socket():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.set_inheritable(True)
    fd_marker = f"\n{listener.fileno()}\n"
    try:
        pid, master_fd = spawn_pty_process(["ls", "/dev/fd"])
        output = "\n" + _read_until_exit(master_fd).replace("\r", "")
        os.close(master_fd)
        os.waitpid(pid, 0)
    finally:
        listener.close()

    assert fd_marker not in output
