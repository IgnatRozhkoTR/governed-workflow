"""LSP server lifecycle management: spawn, track, communicate, and teardown."""
import atexit
import json
import logging
import os
import select
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from core import paths
from core.db import get_db_ctx
from core.helpers import sanitize_branch

logger = logging.getLogger(__name__)

_LSP_PROCESSES = {}
_PROCESS_LOCKS = {}
_request_id_lock = threading.Lock()
_request_id_counter = 0

LSP_CACHE_DIR_PLACEHOLDER = "{lsp_cache_dir}"
LSP_TOOLS_DIR_PLACEHOLDER = "{tools_dir}"


def _next_request_id():
    global _request_id_counter
    with _request_id_lock:
        _request_id_counter += 1
        return _request_id_counter


def _encode_lsp_message(obj):
    """Format a Python dict as a Content-Length-delimited JSON-RPC message."""
    body = json.dumps(obj, separators=(",", ":"))
    body_bytes = body.encode("utf-8")
    header = f"Content-Length: {len(body_bytes)}\r\n\r\n"
    return header.encode("ascii") + body_bytes


def _has_buffered_data(stream):
    """Check if the stream's OS pipe has data available without blocking."""
    buf = getattr(stream, "buffer", stream)
    raw = getattr(buf, "raw", None)
    fd = None
    if raw is not None and hasattr(raw, "fileno"):
        try:
            fd = raw.fileno()
        except (ValueError, OSError):
            return False
    elif hasattr(buf, "fileno"):
        try:
            fd = buf.fileno()
        except (ValueError, OSError):
            return False
    if fd is None:
        return False
    readable, _, _ = select.select([fd], [], [], 0)
    return len(readable) > 0


def _wait_for_readable(stream, timeout):
    """Return True if *stream* has buffered data or becomes OS-readable within *timeout* seconds."""
    if _has_buffered_data(stream):
        return True
    try:
        readable, _, _ = select.select([stream], [], [], timeout)
        return bool(readable)
    except (ValueError, OSError):
        return False


def _read_lsp_message(stdout, timeout=None):
    """Read one Content-Length-delimited JSON-RPC message from *stdout*.

    Returns the parsed dict, or None on EOF / protocol error / timeout.
    When *timeout* is given, waits at most that many seconds for data
    before returning None.
    """
    if timeout is not None and not _wait_for_readable(stdout, timeout):
        return None

    headers = {}
    while True:
        line = stdout.readline()
        if not line:
            return None
        line_str = line.decode("ascii", errors="replace").strip()
        if not line_str:
            break
        if ":" in line_str:
            key, _, value = line_str.partition(":")
            headers[key.strip().lower()] = value.strip()

    length_str = headers.get("content-length")
    if length_str is None:
        logger.warning("LSP message missing Content-Length header")
        return None

    try:
        length = int(length_str)
    except ValueError:
        logger.warning("Invalid Content-Length value: %s", length_str)
        return None

    body = stdout.read(length)
    if len(body) < length:
        return None

    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Malformed JSON in LSP message body")
        return None


def _process_key(project_id, profile_id):
    return (str(project_id), int(profile_id))


# ---------------------------------------------------------------------------
# Persistent LSP cache directories
# ---------------------------------------------------------------------------
#
# lsp_instances is keyed by project_id + profile_id only (no workspace/branch
# component -- see the UNIQUE(project_id, profile_id) constraint and
# _process_key above), so the persistent on-disk cache is scoped the same way.

def _lsp_cache_root():
    """Return the root directory for persistent per-instance LSP cache dirs."""
    return paths.tools_dir() / "lsp-cache"


def lsp_cache_dir(project_id, profile_id):
    """Return the persistent cache directory path for a given (project, profile) instance.

    Nested as ``<project>/<profile>`` rather than a flattened ``project-profile``
    key so that sanitized project ids sharing a common prefix (e.g. ``proj-a``
    and ``proj-a-extra``) can never collide, and so a whole project's cache can
    be removed with a single directory delete.
    """
    return _lsp_cache_root() / sanitize_branch(str(project_id)) / str(profile_id)


def _substitute_lsp_cache_dir(args, project_id, profile_id):
    """Replace the ``{lsp_cache_dir}`` placeholder in profile lsp_args with a persistent dir.

    Creates the directory before returning so the spawned process can write into
    it immediately. Profiles whose args never reference the placeholder are left
    untouched and no directory is created -- this is opt-in per profile.
    """
    if not any(LSP_CACHE_DIR_PLACEHOLDER in arg for arg in args):
        return args
    cache_dir = lsp_cache_dir(project_id, profile_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return [arg.replace(LSP_CACHE_DIR_PLACEHOLDER, str(cache_dir)) for arg in args]


def remove_lsp_cache_dirs(project_id):
    """Best-effort removal of every persistent LSP cache dir for *project_id*.

    Cache dirs nest every profile under the project's own directory, so this
    removes every profile's cache for the project in one delete. Never
    raises: cache directories are a performance optimization, not a source
    of truth, so removal failures are logged and swallowed.
    """
    project_cache_dir = _lsp_cache_root() / sanitize_branch(str(project_id))
    if not project_cache_dir.is_dir():
        return
    try:
        shutil.rmtree(project_cache_dir)
    except OSError:
        logger.warning("Failed to remove LSP cache dir %s", project_cache_dir, exc_info=True)


def _resolve_lsp_command(command):
    """Resolve a profile's lsp_command into the argv prefix used to spawn it.

    Substitutes the ``{tools_dir}`` placeholder with the repo's tools
    directory (``paths.tools_dir``). The resolved path is invoked via
    ``python3`` when it lacks the executable bit -- git does not reliably
    preserve file permissions across every checkout method (zip downloads,
    some CI checkouts), so relying solely on the bit being set would be
    fragile. Commands without the placeholder are returned unchanged,
    matching prior behavior for tools resolved via PATH.
    """
    if LSP_TOOLS_DIR_PLACEHOLDER not in command:
        return [command]
    resolved = command.replace(LSP_TOOLS_DIR_PLACEHOLDER, str(paths.tools_dir()))
    if os.access(resolved, os.X_OK):
        return [resolved]
    return ["python3", resolved]


def _is_pid_alive(pid):
    """Return True if a process with *pid* exists."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _get_lock(key):
    """Return (and lazily create) a threading.Lock for the given process key."""
    return _PROCESS_LOCKS.setdefault(key, threading.Lock())


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_project_lsp_profiles(db, project_id):
    """Return LSP-capable profiles assigned to *project_id* with instance status."""
    rows = db.execute(
        "SELECT pp.id AS assignment_id, pp.lsp_enabled, pp.subpath, "
        "       vp.id AS profile_id, vp.name, vp.language, "
        "       vp.lsp_command, vp.lsp_args, vp.lsp_install_check_command, "
        "       vp.lsp_install_command, vp.lsp_workspace_config, vp.lsp_port, "
        "       li.pid, li.port AS instance_port, li.status AS instance_status, "
        "       li.started_at, li.error_message "
        "FROM project_verification_profiles pp "
        "JOIN verification_profiles vp ON pp.profile_id = vp.id "
        "LEFT JOIN lsp_instances li ON li.project_id = pp.project_id AND li.profile_id = vp.id "
        "WHERE pp.project_id = ? AND vp.lsp_command IS NOT NULL",
        (project_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_lsp_status(db, project_id):
    """Return status of all LSP instances for *project_id*, reaping dead processes."""
    rows = db.execute(
        "SELECT li.*, vp.name AS profile_name "
        "FROM lsp_instances li "
        "JOIN verification_profiles vp ON li.profile_id = vp.id "
        "WHERE li.project_id = ?",
        (project_id,)
    ).fetchall()

    results = []
    for row in rows:
        entry = dict(row)
        if entry["status"] == "running" and entry["pid"]:
            if not _is_pid_alive(entry["pid"]):
                key = _process_key(project_id, entry["profile_id"])
                tracked = _LSP_PROCESSES.get(key)
                if tracked is not None:
                    returncode = tracked["process"].poll()
                    error_message = f"LSP server exited with return code {returncode}"
                else:
                    error_message = "Process died unexpectedly"
                db.execute(
                    "UPDATE lsp_instances SET status = 'error', error_message = ? "
                    "WHERE project_id = ? AND profile_id = ?",
                    (error_message, project_id, entry["profile_id"])
                )
                entry["status"] = "error"
                entry["error_message"] = error_message
                _LSP_PROCESSES.pop(key, None)
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def _initialize_lsp_server(key, workspace_path):
    """Perform the LSP initialize handshake (initialize request + initialized notification).

    Returns the initialize response dict on success, or raises RuntimeError on failure.
    """
    entry = _LSP_PROCESSES.get(key)
    if entry is None:
        raise RuntimeError("LSP process not tracked")

    process = entry["process"]
    if process.poll() is not None:
        raise RuntimeError("LSP process exited before initialization")

    request_id = _next_request_id()
    init_request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "processId": os.getpid(),
            "rootUri": f"file://{workspace_path}",
            "rootPath": workspace_path,
            "capabilities": {
                "textDocument": {
                    "definition": {"dynamicRegistration": False},
                    "hover": {
                        "dynamicRegistration": False,
                        "contentFormat": ["markdown", "plaintext"],
                    },
                    "references": {"dynamicRegistration": False},
                    "synchronization": {
                        "dynamicRegistration": False,
                        "didSave": True,
                        "willSave": False,
                    },
                    "completion": {
                        "dynamicRegistration": False,
                        "completionItem": {"snippetSupport": False},
                    },
                },
            },
            "workspaceFolders": [
                {"uri": f"file://{workspace_path}", "name": os.path.basename(workspace_path)}
            ],
        },
    }

    try:
        process.stdin.write(_encode_lsp_message(init_request))
        process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise RuntimeError(f"Failed to send initialize request: {exc}")

    initialize_timeout_seconds = 300
    deadline = time.time() + initialize_timeout_seconds
    response = None
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise RuntimeError(
                f"Timed out waiting for initialize response ({initialize_timeout_seconds}s). "
                "First-time Gradle import on kotlin-lsp / jdtls can be slow; "
                "subsequent starts reuse the cache."
            )
        response = _read_lsp_message(process.stdout, timeout=remaining)
        if response is None:
            if process.poll() is not None:
                raise RuntimeError(
                    f"LSP server exited (returncode={process.returncode}) "
                    "before responding to initialize"
                )
            continue
        if response.get("id") == request_id:
            break
        if "method" in response:
            logger.debug("LSP init: skipping notification %s", response.get("method"))

    if "error" in response:
        raise RuntimeError(f"LSP initialize returned error: {response['error']}")

    initialized_notification = {
        "jsonrpc": "2.0",
        "method": "initialized",
        "params": {},
    }
    try:
        process.stdin.write(_encode_lsp_message(initialized_notification))
        process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise RuntimeError(f"Failed to send initialized notification: {exc}")

    logger.info("LSP server initialized successfully for key=%s", key)
    return response


def _drain_stderr(process, key):
    """Consume stderr in a background daemon thread to prevent pipe deadlock."""

    def _reader():
        try:
            for raw_line in process.stderr:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line:
                    logger.debug("LSP stderr [%s]: %s", key, line)
        except (ValueError, OSError):
            pass

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()


def _current_process_status(db, project_id, profile_id):
    """Return the DB-recorded status/pid for a profile, used for start/stop no-op replies."""
    row = db.execute(
        "SELECT status, pid FROM lsp_instances WHERE project_id = ? AND profile_id = ?",
        (project_id, profile_id)
    ).fetchone()
    status = row["status"] if row else "stopped"
    result = {"ok": True, "status": status, "no_op": True}
    if row and row["pid"]:
        result["pid"] = row["pid"]
    return result


def start_lsp_server_async(db, project_id, profile_id, workspace_path):
    """Validate the profile, dedupe concurrent starts, and spawn the server in the background.

    Returns immediately: ``{"error": ...}`` for validation failures (caller should
    respond 400), ``{"ok": True, "status": "starting", ...}`` once a background
    thread has been kicked off (caller should respond 202), or ``{"ok": True,
    "status": <current>, "no_op": True}`` when a start/stop is already in flight
    or the server is already running (caller should respond 200). The spawned
    thread performs the actual Popen + initialize handshake and writes the
    final 'running'/'error' status using its own DB connection.
    """
    profile = db.execute(
        "SELECT * FROM verification_profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    if not profile:
        return {"error": "profile_not_found"}

    if not profile["lsp_command"]:
        return {"error": "profile_has_no_lsp_command"}

    key = _process_key(project_id, profile_id)
    lock = _get_lock(key)
    if not lock.acquire(blocking=False):
        return _current_process_status(db, project_id, profile_id)

    existing = db.execute(
        "SELECT pid, status FROM lsp_instances WHERE project_id = ? AND profile_id = ?",
        (project_id, profile_id)
    ).fetchone()
    if (
        existing
        and existing["status"] == "running"
        and existing["pid"]
        and key in _LSP_PROCESSES
        and _is_pid_alive(existing["pid"])
    ):
        lock.release()
        return {"ok": True, "status": "already_running", "pid": existing["pid"]}

    db.execute(
        "INSERT INTO lsp_instances (project_id, profile_id, status) "
        "VALUES (?, ?, 'starting') "
        "ON CONFLICT(project_id, profile_id) DO UPDATE SET status = 'starting', error_message = NULL",
        (project_id, profile_id)
    )
    db.commit()

    thread = threading.Thread(
        target=_start_lsp_server_thread,
        args=(project_id, profile_id, workspace_path, key, lock),
        name=f"lsp-start-{project_id}-{profile_id}",
        daemon=True,
    )
    thread.start()
    return {"ok": True, "status": "starting", "profile_id": profile_id}


def _start_lsp_server_thread(project_id, profile_id, workspace_path, key, lock):
    """Background body of a start: spawn the process, run the handshake, record the result."""
    try:
        with get_db_ctx() as db:
            _start_lsp_server_body(db, project_id, profile_id, workspace_path, key)
    except Exception:
        logger.exception("LSP start thread crashed (project=%s, profile=%s)", project_id, profile_id)
        _LSP_PROCESSES.pop(key, None)
        with get_db_ctx() as db:
            db.execute(
                "UPDATE lsp_instances SET status = 'error', error_message = 'LSP start thread crashed unexpectedly' "
                "WHERE project_id = ? AND profile_id = ?",
                (project_id, profile_id)
            )
            db.commit()
    finally:
        lock.release()


def _start_lsp_server_body(db, project_id, profile_id, workspace_path, key):
    """Spawn an LSP server for the given project/profile and track it.

    Runs inside the background thread started by ``start_lsp_server_async``,
    using the DB connection that thread owns.
    """
    profile = db.execute(
        "SELECT * FROM verification_profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    if not profile or not profile["lsp_command"]:
        error_msg = "LSP profile is no longer available"
        logger.error(error_msg)
        db.execute(
            "UPDATE lsp_instances SET status = 'error', error_message = ? "
            "WHERE project_id = ? AND profile_id = ?",
            (error_msg, project_id, profile_id)
        )
        db.commit()
        return

    existing = db.execute(
        "SELECT pid, status FROM lsp_instances WHERE project_id = ? AND profile_id = ?",
        (project_id, profile_id)
    ).fetchone()
    if existing and existing["pid"] and _is_pid_alive(existing["pid"]) and key not in _LSP_PROCESSES:
        # Orphan: DB says a pid is alive, but the relay lost track of its
        # stdin/stdout pipes (e.g. earlier BrokenPipeError). The unreachable
        # child must be terminated before we spawn a fresh tracked instance,
        # otherwise resources leak.
        logger.warning(
            "Found orphan LSP pid=%s for project=%s profile=%s; terminating before respawn",
            existing["pid"], project_id, profile_id,
        )
        try:
            os.kill(existing["pid"], signal.SIGTERM)
        except OSError:
            pass
        for _ in range(10):
            if not _is_pid_alive(existing["pid"]):
                break
            time.sleep(0.2)
        else:
            try:
                os.kill(existing["pid"], signal.SIGKILL)
            except OSError:
                pass

    lsp_args = _substitute_lsp_cache_dir(
        json.loads(profile["lsp_args"] or "[]"), project_id, profile_id
    )
    cmd = _resolve_lsp_command(profile["lsp_command"]) + lsp_args
    logger.info("Starting LSP server: %s (project=%s, profile=%s)", cmd, project_id, profile_id)

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace_path,
        )
        _drain_stderr(process, key)
    except FileNotFoundError:
        error_msg = f"LSP command not found: {profile['lsp_command']}"
        logger.error(error_msg)
        db.execute(
            "UPDATE lsp_instances SET status = 'error', error_message = ? "
            "WHERE project_id = ? AND profile_id = ?",
            (error_msg, project_id, profile_id)
        )
        db.commit()
        return
    except OSError as exc:
        error_msg = f"Failed to start LSP server: {exc}"
        logger.error(error_msg)
        db.execute(
            "UPDATE lsp_instances SET status = 'error', error_message = ? "
            "WHERE project_id = ? AND profile_id = ?",
            (error_msg, project_id, profile_id)
        )
        db.commit()
        return

    _LSP_PROCESSES[key] = {
        "process": process,
        "profile_id": profile_id,
        "project_id": project_id,
        "workspace_path": workspace_path,
    }

    try:
        _initialize_lsp_server(key, workspace_path)
    except RuntimeError as exc:
        error_msg = f"LSP initialization failed: {exc}"
        logger.error(error_msg)
        _LSP_PROCESSES.pop(key, None)
        try:
            process.terminate()
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            process.kill()
            try:
                process.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                pass
        db.execute(
            "UPDATE lsp_instances SET status = 'error', error_message = ? "
            "WHERE project_id = ? AND profile_id = ?",
            (error_msg, project_id, profile_id),
        )
        db.commit()
        return

    now = datetime.now().isoformat()
    db.execute(
        "UPDATE lsp_instances SET pid = ?, status = 'running', started_at = ?, error_message = NULL "
        "WHERE project_id = ? AND profile_id = ?",
        (process.pid, now, project_id, profile_id)
    )
    db.commit()

    logger.info("LSP server started: pid=%d (project=%s, profile=%s)", process.pid, project_id, profile_id)


def stop_lsp_server_async(db, project_id, profile_id):
    """Mark an LSP server as stopping and terminate it in the background.

    Returns ``{"ok": True, "status": "stopped", ...}`` immediately when there
    is nothing tracked to stop, ``{"ok": True, "status": "stopping", ...}``
    once a background thread has been kicked off (caller should respond 202),
    or the current status as a no-op when a start/stop is already in flight
    for this profile (caller should respond 200).
    """
    key = _process_key(project_id, profile_id)
    lock = _get_lock(key)
    if not lock.acquire(blocking=False):
        return _current_process_status(db, project_id, profile_id)

    entry = _LSP_PROCESSES.pop(key, None)
    if entry is None:
        db.execute(
            "UPDATE lsp_instances SET status = 'stopped', pid = NULL "
            "WHERE project_id = ? AND profile_id = ?",
            (project_id, profile_id)
        )
        db.commit()
        lock.release()
        return {"ok": True, "status": "stopped", "note": "no_tracked_process"}

    db.execute(
        "UPDATE lsp_instances SET status = 'stopping' "
        "WHERE project_id = ? AND profile_id = ?",
        (project_id, profile_id)
    )
    db.commit()

    thread = threading.Thread(
        target=_stop_lsp_server_thread,
        args=(project_id, profile_id, entry, key, lock),
        name=f"lsp-stop-{project_id}-{profile_id}",
        daemon=True,
    )
    thread.start()
    return {"ok": True, "status": "stopping", "profile_id": profile_id}


def _stop_lsp_server_thread(project_id, profile_id, entry, key, lock):
    """Background body of a stop: terminate the process (up to 8s) and record the result."""
    try:
        process = entry["process"]
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("LSP server pid=%d did not terminate, sending SIGKILL", process.pid)
            process.kill()
            try:
                process.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                logger.warning("LSP server pid=%d did not exit after SIGKILL", process.pid)
        except OSError:
            pass

        with get_db_ctx() as db:
            db.execute(
                "UPDATE lsp_instances SET status = 'stopped', pid = NULL "
                "WHERE project_id = ? AND profile_id = ?",
                (project_id, profile_id)
            )
            db.commit()

        logger.info("LSP server stopped (project=%s, profile=%s)", project_id, profile_id)
    except Exception:
        logger.exception("LSP stop thread crashed (project=%s, profile=%s)", project_id, profile_id)
        with get_db_ctx() as db:
            db.execute(
                "UPDATE lsp_instances SET status = 'error', error_message = 'LSP stop thread crashed unexpectedly' "
                "WHERE project_id = ? AND profile_id = ?",
                (project_id, profile_id)
            )
            db.commit()
    finally:
        _PROCESS_LOCKS.pop(key, None)
        lock.release()


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------

def start_all_lsp_servers_async(db, project_id, workspace_path):
    """Kick off a start for every enabled profile of *project_id*, one thread each."""
    profiles = db.execute(
        "SELECT vp.id AS profile_id, vp.name "
        "FROM project_verification_profiles pp "
        "JOIN verification_profiles vp ON pp.profile_id = vp.id "
        "WHERE pp.project_id = ? AND pp.lsp_enabled = 1 AND vp.lsp_command IS NOT NULL",
        (project_id,)
    ).fetchall()
    snapshot = [(row["profile_id"], row["name"]) for row in profiles]

    results = []
    for profile_id, profile_name in snapshot:
        try:
            result = start_lsp_server_async(db, project_id, profile_id, workspace_path)
        except Exception as e:
            logger.exception("start_all_lsp_servers_async failed for id=%s", profile_id)
            result = {"error": str(e)}
        result["profile_id"] = profile_id
        result["profile_name"] = profile_name
        results.append(result)
    return results


def stop_all_lsp_servers_async(db, project_id):
    """Kick off a stop for every running LSP server of *project_id*, one thread each."""
    instances = db.execute(
        "SELECT profile_id FROM lsp_instances WHERE project_id = ? AND status = 'running'",
        (project_id,)
    ).fetchall()
    snapshot = [row["profile_id"] for row in instances]

    results = []
    for profile_id in snapshot:
        try:
            result = stop_lsp_server_async(db, project_id, profile_id)
        except Exception as e:
            logger.exception("stop_all_lsp_servers_async failed for id=%s", profile_id)
            result = {"error": str(e)}
        result["profile_id"] = profile_id
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Install check
# ---------------------------------------------------------------------------

def check_lsp_installed(profile):
    """Return True if the LSP tool required by *profile* is installed."""
    cmd = profile.get("lsp_install_check_command")
    if not cmd:
        return True
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# JSON-RPC communication
# ---------------------------------------------------------------------------

def send_lsp_request(project_id, profile_id, method, params):
    """Send a JSON-RPC request and return the parsed response."""
    key = _process_key(project_id, profile_id)
    entry = _LSP_PROCESSES.get(key)
    if entry is None:
        return {"error": "lsp_server_not_running"}

    lock = _get_lock(key)
    request_id = _next_request_id()
    message = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }

    with lock:
        process = entry["process"]
        if process.poll() is not None:
            _LSP_PROCESSES.pop(key, None)
            return {"error": "lsp_server_process_exited"}

        try:
            process.stdin.write(_encode_lsp_message(message))
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            _LSP_PROCESSES.pop(key, None)
            return {"error": f"failed_to_write: {exc}"}

        deadline = time.time() + 10
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return {"error": "lsp_response_timeout"}
            response = _read_lsp_message(process.stdout, timeout=remaining)
            if response is None:
                if time.time() >= deadline:
                    return {"error": "lsp_response_timeout"}
                return {"error": "no_response_from_lsp_server"}
            if response.get("id") == request_id:
                return response
            if "method" in response:
                logger.debug("LSP notification (skipped): %s", response.get("method"))
            else:
                logger.warning("LSP response with mismatched id: expected=%s, got=%s", request_id, response.get("id"))


def send_lsp_notification(project_id, profile_id, method, params):
    """Send a JSON-RPC notification (no response expected)."""
    key = _process_key(project_id, profile_id)
    entry = _LSP_PROCESSES.get(key)
    if entry is None:
        return {"error": "lsp_server_not_running"}

    lock = _get_lock(key)
    message = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    }

    with lock:
        process = entry["process"]
        if process.poll() is not None:
            _LSP_PROCESSES.pop(key, None)
            return {"error": "lsp_server_process_exited"}

        try:
            process.stdin.write(_encode_lsp_message(message))
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            _LSP_PROCESSES.pop(key, None)
            return {"error": f"failed_to_write: {exc}"}

    return {"ok": True}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def shutdown_all():
    """Terminate every tracked LSP server. Called via atexit on app exit."""
    keys = list(_LSP_PROCESSES.keys())
    for key in keys:
        entry = _LSP_PROCESSES.pop(key, None)
        if entry is None:
            continue
        process = entry["process"]
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                logger.warning("LSP server pid=%d did not exit after SIGKILL", process.pid)
        except OSError:
            pass
    logger.info("All LSP servers shut down (%d total)", len(keys))


atexit.register(shutdown_all)
