"""Extract and format a Claude Code session transcript for a workspace."""
import json
import os
from pathlib import Path


_MAX_TRANSCRIPT_BYTES = 200 * 1024  # 200 KB


class SessionExtractorError(Exception):
    """Raised when the session transcript cannot be located or read."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _project_key(working_dir: str) -> str:
    """Convert an absolute working_dir path to the Claude project key."""
    return working_dir.replace("/", "-")


def _claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _agent_tasks_dir(uid: str, project_key: str, session_uuid: str) -> Path:
    return Path(f"/private/tmp/claude-{uid}") / project_key / session_uuid / "tasks"


def _find_jsonl_for_session(project_dir: Path, session_id: str) -> Path | None:
    candidate = project_dir / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None


def _find_most_recent_jsonl(project_dir: Path, ws_created_at: str | None) -> Path | None:
    """Return the most recently modified *.jsonl in project_dir.

    When ``ws_created_at`` is supplied (ISO-8601 string from the workspace row),
    candidates whose mtime predates the workspace creation are filtered out so
    we don't accidentally select a transcript from before this workspace existed.
    Falsy or unparseable timestamps disable the filter and the original
    "most recently modified" semantics apply.
    """
    if not project_dir.exists():
        return None
    candidates = list(project_dir.glob("*.jsonl"))
    if not candidates:
        return None

    cutoff = _parse_workspace_cutoff(ws_created_at)
    if cutoff is not None:
        eligible = [p for p in candidates if p.stat().st_mtime >= cutoff]
        if eligible:
            candidates = eligible

    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_workspace_cutoff(ws_created_at: str | None) -> float | None:
    if not ws_created_at:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(ws_created_at).timestamp()
    except (TypeError, ValueError):
        return None


def _is_real_user_message(record: dict) -> bool:
    if record.get("type") != "user":
        return False
    if record.get("isMeta"):
        return False
    msg = record.get("message", {})
    content = msg.get("content") if isinstance(msg, dict) else None
    return isinstance(content, str)


def _is_real_assistant_message(record: dict) -> bool:
    if record.get("type") != "assistant":
        return False
    msg = record.get("message", {})
    if not isinstance(msg, dict):
        return False
    content = msg.get("content", [])
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "text"
        for block in content
    )


def _extract_assistant_text(record: dict) -> str:
    msg = record.get("message", {})
    content = msg.get("content", []) if isinstance(msg, dict) else []
    parts = [
        block["text"]
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(parts)


def _parse_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _format_main_transcript(records: list[dict]) -> list[str]:
    lines = []
    for rec in records:
        if _is_real_user_message(rec):
            content = rec["message"]["content"]
            lines.append(f"[USER]: {content}")
        elif _is_real_assistant_message(rec):
            text = _extract_assistant_text(rec)
            if text.strip():
                lines.append(f"[ASSISTANT]: {text}")
    return lines


def _format_agent_output(agent_id: str, task_path: Path) -> list[str]:
    records = _parse_jsonl(task_path)
    lines = []

    input_record = next(
        (
            r for r in records
            if r.get("type") == "user"
            and r.get("parentUuid") is None
            and isinstance(r.get("message", {}).get("content"), str)
        ),
        None,
    )
    if input_record:
        lines.append(f"[SUB-AGENT {agent_id} INPUT]: {input_record['message']['content']}")

    output_record = next(
        (
            r for r in reversed(records)
            if r.get("type") == "assistant"
            and r.get("message", {}).get("stop_reason") == "end_turn"
            and _is_real_assistant_message(r)
        ),
        None,
    )
    if output_record:
        text = _extract_assistant_text(output_record)
        if text.strip():
            lines.append(f"[SUB-AGENT {agent_id} OUTPUT]: {text}")

    return lines


def _count_messages(records: list[dict]) -> int:
    return sum(
        1 for r in records
        if _is_real_user_message(r) or _is_real_assistant_message(r)
    )


def _first_timestamp(records: list[dict]) -> str | None:
    for rec in records:
        ts = rec.get("timestamp") or rec.get("ts")
        if ts:
            return str(ts)
    return None


def _truncate_to_limit(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= _MAX_TRANSCRIPT_BYTES:
        return text
    truncated = encoded[-_MAX_TRANSCRIPT_BYTES:]
    return truncated.decode("utf-8", errors="replace")


def _collect_agent_transcripts(project_key: str, session_uuid: str) -> list[str]:
    uid = str(os.getuid())
    tasks_dir = _agent_tasks_dir(uid, project_key, session_uuid)
    if not tasks_dir.exists():
        return []
    lines = []
    for task_file in sorted(tasks_dir.glob("*.output")):
        agent_id = task_file.stem
        lines.extend(_format_agent_output(agent_id, task_file))
    return lines


def extract_session_transcript(workspace_id: int, db) -> dict:
    """Locate and parse the Claude Code session JSONL for a workspace.

    Parameters
        workspace_id: DB primary key of the workspace row.
        db:           Open sqlite3 connection with Row factory.

    Returns
        {session_id, transcript, message_count, started_at}

    Raises
        SessionExtractorError(code='not_found')        — workspace row missing.
        SessionExtractorError(code='no_session_found') — no JSONL file located.
    """
    ws = db.execute(
        "SELECT id, working_dir, session_id, created FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()
    if ws is None:
        raise SessionExtractorError(
            f"Workspace {workspace_id} not found",
            code="not_found",
        )

    project_key = _project_key(ws["working_dir"])
    project_dir = _claude_projects_dir() / project_key
    session_id = ws["session_id"]

    jsonl_path: Path | None = None
    if session_id:
        jsonl_path = _find_jsonl_for_session(project_dir, session_id)

    if jsonl_path is None:
        session_history = db.execute(
            "SELECT session_id FROM session_history WHERE workspace_id = ? ORDER BY started_at DESC",
            (workspace_id,),
        ).fetchall()
        for row in session_history:
            candidate = _find_jsonl_for_session(project_dir, row["session_id"])
            if candidate:
                jsonl_path = candidate
                session_id = row["session_id"]
                break

    if jsonl_path is None:
        jsonl_path = _find_most_recent_jsonl(project_dir, ws["created"])
        if jsonl_path:
            session_id = jsonl_path.stem

    if jsonl_path is None:
        raise SessionExtractorError(
            f"No session JSONL found for workspace {workspace_id} under {project_dir}",
            code="no_session_found",
        )

    records = _parse_jsonl(jsonl_path)
    message_lines = _format_main_transcript(records)

    agent_lines = _collect_agent_transcripts(project_key, session_id)
    all_lines = message_lines + agent_lines

    transcript = _truncate_to_limit("\n".join(all_lines))
    message_count = _count_messages(records)
    started_at = _first_timestamp(records)

    return {
        "session_id": session_id,
        "transcript": transcript,
        "message_count": message_count,
        "started_at": started_at,
    }
