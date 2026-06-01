"""Assemble the four context blobs a reflection agent reads.

Provides a single entry point that pulls scope, branch diff, review findings,
and session transcript into one frozen dataclass.
"""
import dataclasses
from dataclasses import dataclass
from pathlib import Path

from core.db import ws_field
from services import comment_service
from services import diff_filter
from services import plan_service
from services import session_transcript
from services.session_transcript import SessionTranscriptError


@dataclass(frozen=True)
class ReflectionContext:
    workspace_id: int
    project_id: int
    branch: str
    base_branch: str
    scope: dict
    branch_diff: str
    review_findings: list[dict]
    transcript: list[dict]
    transcript_truncated: bool


def gather_reflection_context(
    db,
    ws,
    *,
    project_path: Path,
    max_transcript_messages: int = 400,
    claude_home: Path | None = None,
) -> ReflectionContext:
    """Gather the four context blobs a reflection agent will read.

    - scope: the workspace's current scope map, or empty dict when unset.
    - branch_diff: unified diff of the feature branch against its base.
    - review_findings: all scope='review' discussions, no resolution filter.
    - transcript: the session messages up to max_transcript_messages from the
      end; empty list when the session file is absent.
    - claude_home: override for the ~/.claude root; used in tests to inject
      a temp directory instead of writing to the real home.
    """
    workspace_id = ws["id"]
    project_id = ws["project_id"]
    branch = ws["branch"]
    base = ws_field(ws, "source_branch") or "main"

    scope = plan_service.get_scope(ws)

    resolved_base = diff_filter.resolve_review_base(project_path, base)
    branch_diff = diff_filter.get_branch_diff(project_path, resolved_base)

    review_findings = comment_service.get_review_issues(db, workspace_id)

    transcript, transcript_truncated = _read_transcript(
        project_path, ws, max_transcript_messages, claude_home=claude_home
    )

    return ReflectionContext(
        workspace_id=workspace_id,
        project_id=project_id,
        branch=branch,
        base_branch=base,
        scope=scope,
        branch_diff=branch_diff,
        review_findings=review_findings,
        transcript=transcript,
        transcript_truncated=transcript_truncated,
    )


def _read_transcript(
    project_path: Path,
    ws,
    max_messages: int,
    *,
    claude_home: Path | None,
) -> tuple[list[dict], bool]:
    session_id = ws_field(ws, "session_id")
    if not session_id:
        return [], False

    try:
        messages = session_transcript.read_session_transcript(
            project_path, session_id,
            claude_home=claude_home,
            max_messages=max_messages,
        )
    except SessionTranscriptError as exc:
        if exc.code == "session_file_not_found":
            return [], False
        raise

    message_dicts = [dataclasses.asdict(m) for m in messages]

    # Approximation: if exactly max_messages were returned the file likely has
    # more — we cannot know without reading past the cap, so we treat the cap
    # as a truncation signal rather than doing a second pass.
    truncated = len(messages) == max_messages

    return message_dicts, truncated
