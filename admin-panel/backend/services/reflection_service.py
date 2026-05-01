"""Reflection generation and persistence for workspace sessions."""
from datetime import datetime

from core import llm_client
from core.llm_client import LLMClientError
from services import session_extractor
from services.session_extractor import SessionExtractorError


_REFLECTION_PROMPT_TEMPLATE = """\
Summarize this Claude Code session as a concise reflection. Output Markdown with sections:
## What was done
## What worked
## What did not work
## Lessons
Then a one-line summary on its own line prefixed with SUMMARY:

Session transcript:
{transcript}"""


class ReflectionServiceError(Exception):
    """Domain error for reflection service operations."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _fetch_workspace(db, workspace_id: int):
    row = db.execute(
        "SELECT id FROM workspaces WHERE id = ?", (workspace_id,)
    ).fetchone()
    return row


def _parse_summary(content_md: str) -> str:
    marker = "\nSUMMARY: "
    idx = content_md.find(marker)
    if idx == -1:
        return ""
    return content_md[idx + len(marker):].split("\n")[0].strip()


def _insert_reflection(db, workspace_id: int, content_md: str, summary: str, session_id: str | None) -> dict:
    now = datetime.utcnow().isoformat()
    cursor = db.execute(
        "INSERT INTO reflections (workspace_id, content_md, summary, session_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (workspace_id, content_md, summary, session_id, now),
    )
    return {
        "id": cursor.lastrowid,
        "workspace_id": workspace_id,
        "content_md": content_md,
        "summary": summary,
        "session_id": session_id,
        "created_at": now,
    }


def run(db, workspace_id: int) -> dict:
    """Generate a reflection for the workspace's latest session and persist it.

    Returns
        {id, workspace_id, content_md, summary, session_id, created_at}

    Raises
        ReflectionServiceError(code='not_found')        — workspace missing.
        ReflectionServiceError(code='no_session_found') — no session JSONL located.
        ReflectionServiceError(code='llm_unconfigured') — no LLM API key set.
        ReflectionServiceError(code='llm_failure')      — LLM call failed.
    """
    if _fetch_workspace(db, workspace_id) is None:
        raise ReflectionServiceError(
            f"Workspace {workspace_id} not found",
            code="not_found",
        )

    try:
        extracted = session_extractor.extract_session_transcript(workspace_id, db)
    except SessionExtractorError as exc:
        raise ReflectionServiceError(str(exc), code=exc.code) from exc

    prompt = _REFLECTION_PROMPT_TEMPLATE.format(transcript=extracted["transcript"])

    try:
        content_md = llm_client.complete(prompt, json_mode=False)
    except LLMClientError as exc:
        if exc.code == "unconfigured":
            raise ReflectionServiceError(str(exc), code="llm_unconfigured") from exc
        raise ReflectionServiceError(str(exc), code="llm_failure") from exc

    summary = _parse_summary(content_md)
    result = _insert_reflection(db, workspace_id, content_md, summary, extracted["session_id"])
    db.commit()
    return result


def get(db, reflection_id: int) -> dict:
    """Fetch a single reflection by ID.

    Raises
        ReflectionServiceError(code='not_found') — reflection missing.
    """
    row = db.execute(
        "SELECT id, workspace_id, content_md, summary, session_id, created_at "
        "FROM reflections WHERE id = ?",
        (reflection_id,),
    ).fetchone()
    if row is None:
        raise ReflectionServiceError(
            f"Reflection {reflection_id} not found",
            code="not_found",
        )
    return dict(row)


def list_reflections(db, workspace_id: int) -> list:
    """Return all reflections for a workspace, newest first.

    Raises
        ReflectionServiceError(code='not_found') — workspace missing.
    """
    if _fetch_workspace(db, workspace_id) is None:
        raise ReflectionServiceError(
            f"Workspace {workspace_id} not found",
            code="not_found",
        )
    rows = db.execute(
        "SELECT id, workspace_id, content_md, summary, session_id, created_at "
        "FROM reflections WHERE workspace_id = ? "
        "ORDER BY created_at DESC",
        (workspace_id,),
    ).fetchall()
    return [dict(r) for r in rows]
