"""Read and parse Claude Code session JSONL transcripts.

Claude Code stores each session as a JSONL file at::

    ~/.claude/projects/<encoded-project-path>/<session_id>.jsonl

where ``<encoded-project-path>`` is the absolute project path with every ``/``
and ``.`` replaced by ``-``. Sub-agent (sidechain) invocations live in a
sibling directory ``<session_id>/subagents/`` with one
``agent-<hash>.jsonl`` + ``agent-<hash>.meta.json`` pair per Agent tool call,
where the meta file's ``toolUseId`` keys it back to the parent Agent tool_use
entry. This module collapses parent + inline sub-agent transcripts into a
single flat list of ``TranscriptMessage`` records suitable for downstream
reflection.
"""
import json
from dataclasses import dataclass
from pathlib import Path

_HOME_CLAUDE = Path.home() / ".claude"
_PROJECTS_DIRNAME = "projects"
_SUBAGENTS_DIRNAME = "subagents"


@dataclass(frozen=True)
class TranscriptMessage:
    role: str
    text: str
    is_sub_agent: bool
    agent_label: str | None


class SessionTranscriptError(Exception):
    """Domain error for session transcript reads.

    Codes:
        session_file_not_found — the session JSONL does not exist at the
            resolved path.
        session_file_malformed — a line in the JSONL could not be JSON-parsed.
    """

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def encode_project_path(path: str | Path) -> str:
    return str(path).replace("/", "-").replace(".", "-")


def session_jsonl_path(
    project_path: str | Path,
    session_id: str,
    *,
    claude_home: Path | None = None,
) -> Path:
    base = claude_home if claude_home is not None else _HOME_CLAUDE
    return base / _PROJECTS_DIRNAME / encode_project_path(project_path) / f"{session_id}.jsonl"


def read_session_transcript(
    project_path: str | Path,
    session_id: str,
    *,
    claude_home: Path | None = None,
    max_messages: int | None = None,
) -> list[TranscriptMessage]:
    jsonl_path = session_jsonl_path(project_path, session_id, claude_home=claude_home)
    if not jsonl_path.is_file():
        raise SessionTranscriptError(
            code="session_file_not_found",
            message=f"Session transcript not found at {jsonl_path}",
        )

    subagent_index = _load_subagent_index(jsonl_path.with_suffix("") / _SUBAGENTS_DIRNAME)
    raw_entries = _parse_jsonl(jsonl_path)
    messages = _entries_to_messages(raw_entries, subagent_index, is_sub_agent=False, agent_label=None)

    if max_messages is not None and max_messages >= 0:
        messages = messages[-max_messages:]
    return messages


def _parse_jsonl(path: Path) -> list[dict]:
    entries: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_number, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                entries.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise SessionTranscriptError(
                    code="session_file_malformed",
                    message=f"Failed to parse {path.name} line {line_number}: {exc.msg}",
                ) from exc
    return entries


@dataclass(frozen=True)
class _SubAgentRecord:
    agent_label: str
    transcript_path: Path


def _load_subagent_index(subagents_dir: Path) -> dict[str, _SubAgentRecord]:
    if not subagents_dir.is_dir():
        return {}

    index: dict[str, _SubAgentRecord] = {}
    for meta_path in subagents_dir.glob("*.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tool_use_id = meta.get("toolUseId")
        agent_label = meta.get("agentType") or meta.get("subagent_type") or "sub-agent"
        if not isinstance(tool_use_id, str) or not tool_use_id:
            continue
        transcript_path = meta_path.with_suffix("").with_suffix(".jsonl")
        if not transcript_path.is_file():
            continue
        index[tool_use_id] = _SubAgentRecord(agent_label=agent_label, transcript_path=transcript_path)
    return index


def _entries_to_messages(
    entries: list[dict],
    subagent_index: dict[str, _SubAgentRecord],
    *,
    is_sub_agent: bool,
    agent_label: str | None,
) -> list[TranscriptMessage]:
    messages: list[TranscriptMessage] = []
    for entry in entries:
        if entry.get("isSidechain") and not is_sub_agent:
            continue
        entry_type = entry.get("type")
        if entry_type not in ("user", "assistant"):
            continue
        message_obj = entry.get("message")
        if not isinstance(message_obj, dict):
            continue

        role = message_obj.get("role")
        if role not in ("user", "assistant"):
            continue

        content = message_obj.get("content")
        text_fragments, agent_tool_calls = _extract_content(content)
        text = "\n".join(fragment for fragment in text_fragments if fragment)

        if text:
            messages.append(TranscriptMessage(
                role=role,
                text=text,
                is_sub_agent=is_sub_agent,
                agent_label=agent_label,
            ))

        for tool_use_id, label in agent_tool_calls:
            messages.extend(_expand_sub_agent(tool_use_id, label, subagent_index))

    return messages


def _extract_content(content) -> tuple[list[str], list[tuple[str, str]]]:
    """Return ``(text_fragments, agent_tool_calls)``.

    ``agent_tool_calls`` is a list of ``(tool_use_id, requested_subagent_type)``
    captured from any ``Agent`` tool_use block so the caller can splice the
    sub-agent transcript in afterwards.
    """
    if isinstance(content, str):
        return ([content] if content else [], [])
    if not isinstance(content, list):
        return ([], [])

    fragments: list[str] = []
    agent_calls: list[tuple[str, str]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                fragments.append(text)
        elif block_type == "tool_result":
            fragments.extend(_extract_tool_result_text(block))
        elif block_type == "tool_use" and block.get("name") == "Agent":
            tool_use_id = block.get("id")
            label = _agent_label_from_input(block.get("input"))
            if isinstance(tool_use_id, str) and tool_use_id:
                agent_calls.append((tool_use_id, label))
    return fragments, agent_calls


def _extract_tool_result_text(block: dict) -> list[str]:
    inner = block.get("content")
    if isinstance(inner, str):
        return [inner] if inner else []
    if not isinstance(inner, list):
        return []

    fragments: list[str] = []
    for inner_block in inner:
        if not isinstance(inner_block, dict):
            continue
        if inner_block.get("type") != "text":
            continue
        text = inner_block.get("text")
        if isinstance(text, str) and text:
            fragments.append(text)
    return fragments


def _agent_label_from_input(tool_input) -> str:
    if isinstance(tool_input, dict):
        candidate = tool_input.get("subagent_type") or tool_input.get("description")
        if isinstance(candidate, str) and candidate:
            return candidate
    return "sub-agent"


def _expand_sub_agent(
    tool_use_id: str,
    requested_label: str,
    subagent_index: dict[str, _SubAgentRecord],
) -> list[TranscriptMessage]:
    record = subagent_index.get(tool_use_id)
    if record is None:
        return [TranscriptMessage(
            role="assistant",
            text=f"[sub_agent {requested_label} run]",
            is_sub_agent=True,
            agent_label=requested_label,
        )]

    try:
        sub_entries = _parse_jsonl(record.transcript_path)
    except SessionTranscriptError:
        return [TranscriptMessage(
            role="assistant",
            text=f"[sub_agent {record.agent_label} run]",
            is_sub_agent=True,
            agent_label=record.agent_label,
        )]

    return _entries_to_messages(
        sub_entries,
        subagent_index={},
        is_sub_agent=True,
        agent_label=record.agent_label,
    )
