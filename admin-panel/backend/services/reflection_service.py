"""Reflection generation and persistence for workspace sessions."""
import json
import sys
from datetime import datetime

from core import llm_client
from core.llm_client import LLMClientError
from services import session_extractor
from services.session_extractor import SessionExtractorError


_REFLECTION_PROMPT_TEMPLATE = """\
You will summarize the Claude Code session AND propose improvements.
Return ONLY a JSON object with this exact shape:

{{
  "report_md": "<full markdown report with sections What was done, What worked, What did not work, Lessons>",
  "summary": "<one-line summary>",
  "proposals": [
    {{
      "type": "<one of memory_write|memory_delete|rule_new|rule_update|agent_new|agent_update|skill_new|skill_update|workflow_improvement>",
      "title": "<short title>",
      "body": "<full markdown text the user reads to decide whether to act on this proposal>"
    }}
  ]
}}

Each proposal is a text recommendation for a human reader. The `type` is a
label so the user can filter proposals by category; nothing executes
automatically. Put the actionable detail in `body` — the user will instruct an
agent how to proceed.

Empty `proposals` array is fine if no improvements are warranted.

Session transcript:
{transcript}"""


class ReflectionServiceError(Exception):
    """Domain error for reflection service operations."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _fetch_workspace(db, workspace_id: int):
    row = db.execute(
        "SELECT id, project_id FROM workspaces WHERE id = ?", (workspace_id,)
    ).fetchone()
    return row


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


def _create_proposals(db, raw_proposals: list, workspace_id: int, project_id: int | None) -> list[int]:
    from services import proposal_service
    from services.proposal_service import ProposalServiceError

    proposal_ids: list[int] = []
    for item in raw_proposals:
        if not isinstance(item, dict):
            print(f"reflection_service: skipping non-dict proposal item {item!r}", file=sys.stderr)
            continue
        try:
            created = proposal_service.create(
                db,
                type=item.get("type", ""),
                title=item.get("title", ""),
                body=item.get("body", ""),
                payload={},
                origin="reflection",
                workspace_id=workspace_id,
                project_id=project_id,
                commit=False,
            )
            proposal_ids.append(created["id"])
        except (ValueError, ProposalServiceError) as exc:
            print(f"reflection_service: skipping proposal {item!r}: {exc}", file=sys.stderr)
    return proposal_ids


def run(db, workspace_id: int) -> dict:
    """Generate a reflection for the workspace's latest session and persist it.

    Returns
        {id, workspace_id, content_md, summary, session_id, created_at, proposal_ids}

    Raises
        ReflectionServiceError(code='not_found')        — workspace missing.
        ReflectionServiceError(code='no_session_found') — no session JSONL located.
        ReflectionServiceError(code='llm_unconfigured') — no LLM API key set.
        ReflectionServiceError(code='llm_failure')      — LLM call failed.
        ReflectionServiceError(code='llm_invalid_json') — LLM returned malformed JSON.
    """
    workspace = _fetch_workspace(db, workspace_id)
    if workspace is None:
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
        raw_response = llm_client.complete(prompt, json_mode=True)
    except LLMClientError as exc:
        if exc.code == "unconfigured":
            raise ReflectionServiceError(str(exc), code="llm_unconfigured") from exc
        raise ReflectionServiceError(str(exc), code="llm_failure") from exc

    try:
        parsed = json.loads(raw_response)
    except (ValueError, TypeError) as exc:
        raise ReflectionServiceError(
            f"LLM returned malformed JSON: {exc}",
            code="llm_invalid_json",
        ) from exc

    if not isinstance(parsed, dict):
        raise ReflectionServiceError(
            f"LLM JSON root must be an object, got {type(parsed).__name__}",
            code="llm_invalid_json",
        )

    content_md = parsed.get("report_md", "")
    summary = parsed.get("summary", "")
    raw_proposals = parsed.get("proposals") or []
    if not isinstance(raw_proposals, list):
        raw_proposals = []

    project_id = workspace["project_id"] if workspace["project_id"] is not None else None

    # Insert reflection and proposals inside a single transaction so that a
    # failure in proposal creation rolls back the reflection row too — no
    # orphaned reflection rows without their proposals.
    result = _insert_reflection(db, workspace_id, content_md, summary, extracted["session_id"])
    try:
        proposal_ids = _create_proposals(db, raw_proposals, workspace_id, project_id)
    except Exception:
        db.rollback()
        raise
    db.commit()

    result["proposal_ids"] = proposal_ids
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
