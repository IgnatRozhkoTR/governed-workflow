"""Tests for services.session_transcript."""
import json
from pathlib import Path

import pytest

from services.session_transcript import (
    SessionTranscriptError,
    TranscriptMessage,
    encode_project_path,
    read_session_transcript,
    session_jsonl_path,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line))
            fh.write("\n")


def _session_path(claude_home: Path, project_path: str, session_id: str) -> Path:
    return claude_home / "projects" / encode_project_path(project_path) / f"{session_id}.jsonl"


def _user_text_entry(text: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": text},
    }


def _assistant_block_entry(content_blocks: list[dict]) -> dict:
    return {
        "type": "assistant",
        "isSidechain": False,
        "message": {"role": "assistant", "content": content_blocks},
    }


def _user_block_entry(content_blocks: list[dict]) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": content_blocks},
    }


# ── encode_project_path ───────────────────────────────────────────────────────


def test_encode_project_path_replaces_slashes_and_dots_with_dashes():
    encoded = encode_project_path("/Users/ig/Projects/governed-workflow/.claude/worktrees/new-mode")

    assert encoded == "-Users-ig-Projects-governed-workflow--claude-worktrees-new-mode"


def test_encode_project_path_accepts_path_object():
    encoded = encode_project_path(Path("/a/b.c/d"))

    assert encoded == "-a-b-c-d"


# ── session_jsonl_path ────────────────────────────────────────────────────────


def test_session_jsonl_path_composes_correct_path(tmp_path):
    claude_home = tmp_path / "claude_home"

    result = session_jsonl_path(
        "/Users/ig/Projects/example",
        "session-abc",
        claude_home=claude_home,
    )

    expected = claude_home / "projects" / "-Users-ig-Projects-example" / "session-abc.jsonl"
    assert result == expected


# ── read_session_transcript ───────────────────────────────────────────────────


def test_read_session_transcript_returns_user_and_assistant_text_messages(tmp_path):
    claude_home = tmp_path / "claude_home"
    project = "/Users/test/proj"
    session_id = "sess-1"
    jsonl = _session_path(claude_home, project, session_id)
    _write_jsonl(jsonl, [
        {"type": "summary", "summary": "ignored"},
        _user_text_entry("hello world"),
        _assistant_block_entry([{"type": "text", "text": "hi there"}]),
        {"type": "system", "subtype": "ignored"},
    ])

    messages = read_session_transcript(project, session_id, claude_home=claude_home)

    assert messages == [
        TranscriptMessage(role="user", text="hello world", is_sub_agent=False, agent_label=None),
        TranscriptMessage(role="assistant", text="hi there", is_sub_agent=False, agent_label=None),
    ]


def test_read_session_transcript_skips_tool_use_blocks(tmp_path):
    claude_home = tmp_path / "claude_home"
    project = "/proj"
    session_id = "sess"
    jsonl = _session_path(claude_home, project, session_id)
    _write_jsonl(jsonl, [
        _assistant_block_entry([
            {"type": "text", "text": "running a command"},
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}},
        ]),
    ])

    messages = read_session_transcript(project, session_id, claude_home=claude_home)

    assert len(messages) == 1
    assert messages[0].text == "running a command"
    assert "ls" not in messages[0].text


def test_read_session_transcript_keeps_textual_tool_result_blocks(tmp_path):
    claude_home = tmp_path / "claude_home"
    project = "/proj"
    session_id = "sess"
    jsonl = _session_path(claude_home, project, session_id)
    _write_jsonl(jsonl, [
        _user_block_entry([
            {
                "tool_use_id": "toolu_1",
                "type": "tool_result",
                "content": "file contents here",
            },
        ]),
        _user_block_entry([
            {
                "tool_use_id": "toolu_2",
                "type": "tool_result",
                "content": [
                    {"type": "text", "text": "block one"},
                    {"type": "text", "text": "block two"},
                ],
            },
        ]),
    ])

    messages = read_session_transcript(project, session_id, claude_home=claude_home)

    assert [m.text for m in messages] == ["file contents here", "block one\nblock two"]
    assert all(m.role == "user" for m in messages)


def test_read_session_transcript_skips_image_tool_result_blocks(tmp_path):
    claude_home = tmp_path / "claude_home"
    project = "/proj"
    session_id = "sess"
    jsonl = _session_path(claude_home, project, session_id)
    _write_jsonl(jsonl, [
        _user_block_entry([
            {
                "tool_use_id": "toolu_1",
                "type": "tool_result",
                "content": [
                    {"type": "image", "source": {"type": "base64", "data": "AAA"}},
                ],
            },
        ]),
        _user_block_entry([
            {
                "tool_use_id": "toolu_2",
                "type": "tool_result",
                "content": [
                    {"type": "text", "text": "kept"},
                    {"type": "image", "source": {"type": "base64", "data": "BBB"}},
                ],
            },
        ]),
    ])

    messages = read_session_transcript(project, session_id, claude_home=claude_home)

    assert len(messages) == 1
    assert messages[0].text == "kept"


def test_read_session_transcript_raises_when_file_missing(tmp_path):
    claude_home = tmp_path / "claude_home"

    with pytest.raises(SessionTranscriptError) as exc_info:
        read_session_transcript("/missing", "no-such-session", claude_home=claude_home)

    assert exc_info.value.code == "session_file_not_found"


def test_read_session_transcript_raises_when_line_unparseable(tmp_path):
    claude_home = tmp_path / "claude_home"
    project = "/proj"
    session_id = "sess"
    jsonl = _session_path(claude_home, project, session_id)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text(
        json.dumps(_user_text_entry("ok")) + "\n"
        + "not valid json\n",
        encoding="utf-8",
    )

    with pytest.raises(SessionTranscriptError) as exc_info:
        read_session_transcript(project, session_id, claude_home=claude_home)

    assert exc_info.value.code == "session_file_malformed"
    assert "line 2" in str(exc_info.value)


def test_read_session_transcript_caps_to_max_messages_from_end(tmp_path):
    claude_home = tmp_path / "claude_home"
    project = "/proj"
    session_id = "sess"
    jsonl = _session_path(claude_home, project, session_id)
    _write_jsonl(jsonl, [
        _user_text_entry("one"),
        _assistant_block_entry([{"type": "text", "text": "two"}]),
        _user_text_entry("three"),
        _assistant_block_entry([{"type": "text", "text": "four"}]),
    ])

    messages = read_session_transcript(project, session_id, claude_home=claude_home, max_messages=2)

    assert [m.text for m in messages] == ["three", "four"]


def test_read_session_transcript_inlines_sub_agent_transcript_from_subagents_dir(tmp_path):
    claude_home = tmp_path / "claude_home"
    project = "/proj"
    session_id = "sess"
    jsonl = _session_path(claude_home, project, session_id)
    _write_jsonl(jsonl, [
        _user_text_entry("delegate this"),
        _assistant_block_entry([
            {"type": "text", "text": "delegating to sub-agent"},
            {
                "type": "tool_use",
                "id": "toolu_subagent_1",
                "name": "Agent",
                "input": {
                    "subagent_type": "code-researcher",
                    "description": "look up X",
                    "prompt": "do thing",
                },
            },
        ]),
    ])

    subagents_dir = jsonl.with_suffix("") / "subagents"
    subagents_dir.mkdir(parents=True, exist_ok=True)
    meta_path = subagents_dir / "agent-abc.meta.json"
    meta_path.write_text(json.dumps({
        "toolUseId": "toolu_subagent_1",
        "agentType": "code-researcher",
        "description": "look up X",
    }), encoding="utf-8")
    sub_transcript = subagents_dir / "agent-abc.jsonl"
    _write_jsonl(sub_transcript, [
        {
            "type": "user",
            "isSidechain": True,
            "message": {"role": "user", "content": "sub prompt"},
        },
        {
            "type": "assistant",
            "isSidechain": True,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "sub answer"}]},
        },
    ])

    messages = read_session_transcript(project, session_id, claude_home=claude_home)

    assert messages == [
        TranscriptMessage(role="user", text="delegate this", is_sub_agent=False, agent_label=None),
        TranscriptMessage(role="assistant", text="delegating to sub-agent", is_sub_agent=False, agent_label=None),
        TranscriptMessage(role="user", text="sub prompt", is_sub_agent=True, agent_label="code-researcher"),
        TranscriptMessage(role="assistant", text="sub answer", is_sub_agent=True, agent_label="code-researcher"),
    ]


def test_read_session_transcript_emits_stub_when_sub_agent_transcript_missing(tmp_path):
    claude_home = tmp_path / "claude_home"
    project = "/proj"
    session_id = "sess"
    jsonl = _session_path(claude_home, project, session_id)
    _write_jsonl(jsonl, [
        _assistant_block_entry([
            {
                "type": "tool_use",
                "id": "toolu_orphan",
                "name": "Agent",
                "input": {
                    "subagent_type": "logic-reviewer",
                    "description": "review",
                    "prompt": "...",
                },
            },
        ]),
    ])

    messages = read_session_transcript(project, session_id, claude_home=claude_home)

    assert messages == [
        TranscriptMessage(
            role="assistant",
            text="[sub_agent logic-reviewer run]",
            is_sub_agent=True,
            agent_label="logic-reviewer",
        ),
    ]


def test_read_session_transcript_skips_main_session_sidechain_lines(tmp_path):
    """Sidechain lines in the main JSONL would double-count sub-agent content
    when the subagents/ dir already holds the canonical transcript."""
    claude_home = tmp_path / "claude_home"
    project = "/proj"
    session_id = "sess"
    jsonl = _session_path(claude_home, project, session_id)
    _write_jsonl(jsonl, [
        _user_text_entry("main user"),
        {
            "type": "user",
            "isSidechain": True,
            "message": {"role": "user", "content": "should be skipped"},
        },
    ])

    messages = read_session_transcript(project, session_id, claude_home=claude_home)

    assert [m.text for m in messages] == ["main user"]
