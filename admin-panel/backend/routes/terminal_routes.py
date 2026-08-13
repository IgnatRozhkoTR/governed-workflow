"""Terminal WebSocket and REST routes for tmux session management."""
import json
import re
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_sock import Sock

from core.auth import websocket_auth_ok
from core.terminal import (
    SESSION_KIND_CLAUDE,
    TMUX_NOT_INSTALLED,
    build_claude_command,
    copy_image_to_host_clipboard,
    create_session,
    get_session_command,
    kill_session,
    list_sessions,
    mark_new_session,
    run_pty_websocket,
    send_keys,
    send_paste_keystroke,
    send_prompt,
    session_exists,
    session_name,
    tmux_available,
    write_launch_env_file,
)
from core.db import get_db_ctx, ws_field
from core.helpers import find_workspace

_SAFE_NOTIFY_RE = re.compile(r'[^a-zA-Z0-9 .,!?\-_\'\"():;/]')
_MAX_NOTIFY_LENGTH = 300

bp = Blueprint('terminal', __name__)


def _validate_session_kind(session_kind):
    if session_kind in (None, "", SESSION_KIND_CLAUDE):
        return SESSION_KIND_CLAUDE
    return None


def _terminal_session_name(project, branch, session_kind):
    kind = _validate_session_kind(session_kind)
    if kind is None:
        return None
    return session_name(project, branch, kind=kind)


def _websocket_auth_ok() -> bool:
    with get_db_ctx() as db:
        return websocket_auth_ok(db, request.args.get('token', ''))


def _attach_terminal_ws(ws, project, branch, session_kind):
    if not _websocket_auth_ok():
        ws.send(json.dumps({'error': 'authentication_required'}))
        return

    if not tmux_available():
        ws.send(json.dumps({'error': TMUX_NOT_INSTALLED}))
        return

    name = _terminal_session_name(project, branch, session_kind)
    if not name:
        ws.send(json.dumps({'error': 'Unsupported terminal session kind'}))
        return

    if not session_exists(name):
        ws.send(json.dumps({'error': 'No tmux session. Use Start or Resume first.'}))
        return

    run_pty_websocket(ws, name)


def _attach_terminal_ws_by_name(ws, name):
    """Attach to a tmux session by its exact name.

    Validates against ``list_sessions()`` rather than ``session_exists()``:
    ``tmux has-session`` performs prefix matching on the target name, which
    would let a client attach to an unintended session by supplying a prefix
    of a real session name. The REST listing endpoint already treats
    ``list_sessions()`` as the authoritative set of attachable sessions, so
    reusing it here keeps the allowlist exact and consistent with what the
    frontend displays.
    """
    if not _websocket_auth_ok():
        ws.send(json.dumps({'error': 'authentication_required'}))
        return

    live_session_names = {session['name'] for session in list_sessions()}
    if name not in live_session_names:
        ws.send(json.dumps({'error': 'No tmux session. Use Start or Resume first.'}))
        return

    run_pty_websocket(ws, name)


def register_terminal_ws(app):
    """Register WebSocket routes on the Flask app."""
    sock = Sock(app)

    @sock.route('/ws/terminal/<project>/<path:branch>')
    def terminal_ws(ws, project, branch):
        _attach_terminal_ws(ws, project, branch, SESSION_KIND_CLAUDE)

    @sock.route('/ws/terminal/<project>/<path:branch>/<session_kind>')
    def terminal_ws_kind(ws, project, branch, session_kind):
        _attach_terminal_ws(ws, project, branch, session_kind)

    @sock.route('/ws/terminal-session/<name>')
    def terminal_ws_by_name(ws, name):
        _attach_terminal_ws_by_name(ws, name)


@bp.route('/api/terminal/sessions', methods=['GET'])
def list_terminal_sessions():
    """List all running tmux sessions."""
    sessions = list_sessions()
    for s in sessions:
        s['command'] = get_session_command(s['name'])
    return jsonify(sessions)


@bp.route('/api/terminal/sessions/<name>/kill', methods=['POST'])
def kill_terminal_session_by_name(name):
    """Kill a tmux session by name."""
    if not session_exists(name):
        return jsonify({'ok': False, 'status': 'not_found'}), 404
    kill_session(name)
    return jsonify({'ok': True, 'status': 'killed'})


@bp.route('/api/ws/<project>/<path:branch>/terminal/start', methods=['POST'])
def terminal_start(project, branch):
    """Create tmux session and start Claude Code."""
    if not tmux_available():
        return jsonify({'error': TMUX_NOT_INSTALLED}), 503

    with get_db_ctx() as db:
        ws = find_workspace(db, project, branch)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404

        name = session_name(project, branch)
        working_dir = ws['working_dir']

        if session_exists(name):
            kill_session(name)

        data = request.get_json(silent=True)
        channels = data.get('channels', '') if data else ''

        label = ws['sanitized_branch'] or branch
        create_session(name, working_dir, env={'WORKSPACE': label})
        write_launch_env_file(working_dir, ws_field(ws, 'env_vars', ''))
        mark_new_session(working_dir)
        send_keys(name, build_claude_command(ws, channels=channels))

        return jsonify({
            'session': name,
            'attach_command': f'tmux attach -t {name}',
            'status': 'started'
        })


@bp.route('/api/ws/<project>/<path:branch>/terminal/resume', methods=['POST'])
def terminal_resume(project, branch):
    """Resume Claude Code session in tmux."""
    if not tmux_available():
        return jsonify({'error': TMUX_NOT_INSTALLED}), 503

    with get_db_ctx() as db:
        ws = find_workspace(db, project, branch)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404

        name = session_name(project, branch)
        working_dir = ws['working_dir']

        data = request.get_json(silent=True)
        channels = data.get('channels', '') if data else ''

        created = False
        if not session_exists(name):
            label = ws['sanitized_branch'] or branch
            create_session(name, working_dir, env={'WORKSPACE': label})
            write_launch_env_file(working_dir, ws_field(ws, 'env_vars', ''))
            send_keys(name, build_claude_command(ws, resume=True, channels=channels))
            created = True

        return jsonify({
            'session': name,
            'attach_command': f'tmux attach -t {name}',
            'status': 'created' if created else 'attached'
        })


@bp.route('/api/ws/<project>/<path:branch>/command', methods=['GET'])
def get_command_config(project, branch):
    with get_db_ctx() as db:
        ws = find_workspace(db, project, branch)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404
        return jsonify({
            'claude_command': ws['claude_command'] or 'claude',
            'skip_permissions': bool(ws['skip_permissions']),
            'restrict_to_workspace': bool(ws_field(ws, 'restrict_to_workspace', 1)),
            'allowed_external_paths': ws_field(ws, 'allowed_external_paths', '/tmp/'),
            'env_vars': ws_field(ws, 'env_vars', ''),
        })


@bp.route('/api/ws/<project>/<path:branch>/command', methods=['PUT'])
def update_command_config(project, branch):
    with get_db_ctx() as db:
        data = request.get_json() or {}

        updates = []
        params = []

        if 'claude_command' in data:
            cmd = (data['claude_command'] or '').strip() or 'claude'
            updates.append('claude_command = ?')
            params.append(cmd)

        if 'skip_permissions' in data:
            updates.append('skip_permissions = ?')
            params.append(1 if data['skip_permissions'] else 0)

        if 'restrict_to_workspace' in data:
            updates.append('restrict_to_workspace = ?')
            params.append(1 if data['restrict_to_workspace'] else 0)

        if 'allowed_external_paths' in data:
            updates.append('allowed_external_paths = ?')
            params.append((data['allowed_external_paths'] or '').strip() or '/tmp/')

        if 'env_vars' in data:
            updates.append('env_vars = ?')
            params.append(data['env_vars'] or '')

        if not updates:
            return jsonify({'error': 'No fields to update'}), 400

        ws = find_workspace(db, project, branch)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404

        params.append(ws['id'])
        db.execute("UPDATE workspaces SET " + ", ".join(updates) + " WHERE id = ?", params)
        db.commit()

        if 'env_vars' in data and ws['working_dir']:
            write_launch_env_file(ws['working_dir'], data['env_vars'] or '')

        return jsonify({'ok': True})


@bp.route('/api/ws/<project>/<path:branch>/terminal/status', methods=['GET'])
def terminal_status(project, branch):
    """Check if tmux session exists."""
    if not tmux_available():
        return jsonify({'error': TMUX_NOT_INSTALLED}), 503

    session_kind = _validate_session_kind(request.args.get('kind', SESSION_KIND_CLAUDE))
    if session_kind is None:
        return jsonify({'error': 'Unsupported terminal session kind'}), 400

    name = session_name(project, branch, kind=session_kind)
    return jsonify({
        'session': name,
        'exists': session_exists(name),
        'attach_command': f'tmux attach -t {name}',
        'kind': session_kind,
    })


@bp.route('/api/ws/<project>/<path:branch>/terminal/notify', methods=['POST'])
def terminal_notify(project, branch):
    """Send a notification message to the active tmux session."""
    if not tmux_available():
        return jsonify({'error': 'tmux is not installed'}), 503

    name = session_name(project, branch)
    if not session_exists(name):
        return jsonify({'error': 'No active tmux session'}), 404

    data = request.get_json() or {}
    raw_message = data.get('message', 'New review comments have been left. Please check workspace_get_comments.')
    message = _SAFE_NOTIFY_RE.sub('', raw_message)[:_MAX_NOTIFY_LENGTH].strip()

    if not message:
        return jsonify({'error': 'Message is empty after sanitization'}), 400

    send_prompt(name, message)
    return jsonify({'ok': True, 'status': 'notified'})


@bp.route('/api/ws/<project>/<path:branch>/terminal/kill', methods=['POST'])
def terminal_kill(project, branch):
    """Kill the tmux session."""
    if not tmux_available():
        return jsonify({'error': 'tmux is not installed'}), 503

    data = request.get_json(silent=True) or {}
    session_kind = _validate_session_kind(data.get('kind', SESSION_KIND_CLAUDE))
    if session_kind is None:
        return jsonify({'error': 'Unsupported terminal session kind'}), 400

    name = session_name(project, branch, kind=session_kind)
    if session_exists(name):
        kill_session(name)
    return jsonify({'ok': True, 'status': 'killed', 'kind': session_kind})


@bp.route('/api/ws/<project>/<path:branch>/terminal/paste-image', methods=['POST'])
def terminal_paste_image(project, branch):
    """Persist an uploaded image and return a path Claude Code can attach."""
    with get_db_ctx() as db:
        ws = find_workspace(db, project, branch)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404
        working_dir = ws['working_dir']

    file = request.files.get('image')
    if file is None or not file.filename:
        return jsonify({'error': 'No image provided'}), 400

    content_type = (file.mimetype or '').lower()
    if not content_type.startswith('image/'):
        return jsonify({'error': 'Uploaded file is not an image'}), 400

    ext = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/jpg': '.jpg',
           'image/gif': '.gif', 'image/webp': '.webp'}.get(content_type, '.png')

    dest_dir = Path(working_dir) / '.claude' / 'state' / 'pasted-images'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (uuid.uuid4().hex + ext)
    file.save(str(dest))

    mode = 'path'
    if copy_image_to_host_clipboard(str(dest)):
        name = session_name(project, branch)
        if session_exists(name) and send_paste_keystroke(name):
            mode = 'clipboard'

    return jsonify({'ok': True, 'mode': mode, 'path': str(dest)})
