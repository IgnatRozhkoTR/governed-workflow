"""Tests for session_extractor.extract_session_transcript."""
import json
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.session_extractor import SessionExtractorError, extract_session_transcript


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsonl_lines(*records: dict) -> str:
    return "\n".join(json.dumps(r) for r in records) + "\n"


def _user_record(text: str, *, is_meta: bool = False) -> dict:
    return {
        "type": "user",
        "isMeta": is_meta,
        "message": {"content": text},
        "timestamp": "2024-01-01T10:00:00",
    }


def _assistant_text_record(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
        "timestamp": "2024-01-01T10:01:00",
    }


def _assistant_thinking_record() -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "thinking", "thinking": "internal reasoning"}]},
        "timestamp": "2024-01-01T10:02:00",
    }


def _assistant_tool_use_record() -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]},
        "timestamp": "2024-01-01T10:03:00",
    }


def _user_tool_result_record() -> dict:
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "done"}]},
        "timestamp": "2024-01-01T10:04:00",
    }


def _make_workspace(db, working_dir: str, session_id: str | None = None) -> int:
    cursor = db.execute(
        "INSERT INTO workspaces "
        "(project_id, branch, sanitized_branch, working_dir, created, status, phase, scope_json, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, '2024-01-01', 'active', '0', '{}', '{}', 'main')",
        ("test-project", "feature/test", "feature-test", working_dir),
    )
    ws_id = cursor.lastrowid
    if session_id:
        db.execute("UPDATE workspaces SET session_id = ? WHERE id = ?", (session_id, ws_id))
    db.commit()
    return ws_id


def _make_project(db) -> None:
    db.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        ("test-project", "Test Project", "/tmp/test", "2024-01-01"),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Fixture: patch Path.home() to tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a temporary directory."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExtractBasicTranscript:
    def test_extract_returns_transcript_for_known_session_id(self, clean_db, fake_home):
        from core.db import get_db

        working_dir = "/projects/myapp"
        session_id = "abc123"
        project_key = working_dir.replace("/", "-")
        project_dir = fake_home / ".claude" / "projects" / project_key
        project_dir.mkdir(parents=True)

        records = [
            _user_record("Hello Claude"),
            _assistant_text_record("Hello! How can I help?"),
            _user_tool_result_record(),
        ]
        (project_dir / f"{session_id}.jsonl").write_text(_jsonl_lines(*records))

        db = get_db()
        try:
            _make_project(db)
            ws_id = _make_workspace(db, working_dir, session_id)
            result = extract_session_transcript(ws_id, db)
        finally:
            db.close()

        assert result["session_id"] == session_id
        assert "[USER]: Hello Claude" in result["transcript"]
        assert "[ASSISTANT]: Hello! How can I help?" in result["transcript"]
        assert result["message_count"] == 2
        assert result["started_at"] is not None

    def test_extract_filters_thinking_only_assistant_records(self, clean_db, fake_home):
        from core.db import get_db

        working_dir = "/projects/thinkapp"
        session_id = "think001"
        project_key = working_dir.replace("/", "-")
        project_dir = fake_home / ".claude" / "projects" / project_key
        project_dir.mkdir(parents=True)

        records = [
            _user_record("Do some work"),
            _assistant_thinking_record(),
            _assistant_text_record("Done!"),
        ]
        (project_dir / f"{session_id}.jsonl").write_text(_jsonl_lines(*records))

        db = get_db()
        try:
            _make_project(db)
            ws_id = _make_workspace(db, working_dir, session_id)
            result = extract_session_transcript(ws_id, db)
        finally:
            db.close()

        assert "internal reasoning" not in result["transcript"]
        assert "[ASSISTANT]: Done!" in result["transcript"]

    def test_extract_filters_tool_use_only_assistant_records(self, clean_db, fake_home):
        from core.db import get_db

        working_dir = "/projects/toolapp"
        session_id = "tool001"
        project_key = working_dir.replace("/", "-")
        project_dir = fake_home / ".claude" / "projects" / project_key
        project_dir.mkdir(parents=True)

        records = [
            _user_record("Run a command"),
            _assistant_tool_use_record(),
            _assistant_text_record("Command completed."),
        ]
        (project_dir / f"{session_id}.jsonl").write_text(_jsonl_lines(*records))

        db = get_db()
        try:
            _make_project(db)
            ws_id = _make_workspace(db, working_dir, session_id)
            result = extract_session_transcript(ws_id, db)
        finally:
            db.close()

        assert "tool_use" not in result["transcript"]
        assert "[ASSISTANT]: Command completed." in result["transcript"]

    def test_extract_filters_user_tool_results(self, clean_db, fake_home):
        from core.db import get_db

        working_dir = "/projects/resultapp"
        session_id = "result001"
        project_key = working_dir.replace("/", "-")
        project_dir = fake_home / ".claude" / "projects" / project_key
        project_dir.mkdir(parents=True)

        records = [
            _user_record("Start task"),
            _assistant_tool_use_record(),
            _user_tool_result_record(),
            _assistant_text_record("Task done."),
        ]
        (project_dir / f"{session_id}.jsonl").write_text(_jsonl_lines(*records))

        db = get_db()
        try:
            _make_project(db)
            ws_id = _make_workspace(db, working_dir, session_id)
            result = extract_session_transcript(ws_id, db)
        finally:
            db.close()

        assert "tool_result" not in result["transcript"]
        assert "[USER]: Start task" in result["transcript"]
        assert "[ASSISTANT]: Task done." in result["transcript"]


class TestExtractSubagentTranscripts:
    def test_extract_appends_subagent_transcripts(self, clean_db, fake_home, monkeypatch):
        from core.db import get_db
        import os

        working_dir = "/projects/agentapp"
        session_id = "sess001"
        project_key = working_dir.replace("/", "-")
        project_dir = fake_home / ".claude" / "projects" / project_key
        project_dir.mkdir(parents=True)

        main_records = [_user_record("Do something"), _assistant_text_record("OK")]
        (project_dir / f"{session_id}.jsonl").write_text(_jsonl_lines(*main_records))

        uid = str(os.getuid())
        tasks_dir = Path(f"/private/tmp/claude-{uid}") / project_key / session_id / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        sub_input = {
            "type": "user",
            "parentUuid": None,
            "message": {"content": "Implement the feature"},
            "timestamp": "2024-01-01T11:00:00",
        }
        sub_output = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Feature implemented."}],
                "stop_reason": "end_turn",
            },
            "timestamp": "2024-01-01T11:10:00",
        }
        (tasks_dir / "agent-42.output").write_text(_jsonl_lines(sub_input, sub_output))

        db = get_db()
        try:
            _make_project(db)
            ws_id = _make_workspace(db, working_dir, session_id)
            result = extract_session_transcript(ws_id, db)
        finally:
            db.close()

        assert "[SUB-AGENT agent-42 INPUT]: Implement the feature" in result["transcript"]
        assert "[SUB-AGENT agent-42 OUTPUT]: Feature implemented." in result["transcript"]


class TestExtractTruncation:
    def test_extract_caps_transcript_at_200kb(self, clean_db, fake_home):
        from core.db import get_db

        working_dir = "/projects/bigapp"
        session_id = "big001"
        project_key = working_dir.replace("/", "-")
        project_dir = fake_home / ".claude" / "projects" / project_key
        project_dir.mkdir(parents=True)

        # Build a transcript that exceeds 200 KB
        large_message = "x" * 10_000
        records = []
        for i in range(30):
            records.append(_user_record(f"Message {i}: {large_message}"))
            records.append(_assistant_text_record(f"Reply {i}: {large_message}"))
        tail_user = "final user message at the end"
        tail_assistant = "final assistant reply at the end"
        records.append(_user_record(tail_user))
        records.append(_assistant_text_record(tail_assistant))

        (project_dir / f"{session_id}.jsonl").write_text(_jsonl_lines(*records))

        db = get_db()
        try:
            _make_project(db)
            ws_id = _make_workspace(db, working_dir, session_id)
            result = extract_session_transcript(ws_id, db)
        finally:
            db.close()

        encoded_size = len(result["transcript"].encode("utf-8"))
        assert encoded_size <= 200 * 1024
        assert tail_assistant in result["transcript"]


class TestExtractErrorCases:
    def test_extract_raises_no_session_found_when_dir_empty(self, clean_db, fake_home):
        from core.db import get_db

        working_dir = "/projects/emptyapp"
        project_key = working_dir.replace("/", "-")
        project_dir = fake_home / ".claude" / "projects" / project_key
        project_dir.mkdir(parents=True)

        db = get_db()
        try:
            _make_project(db)
            ws_id = _make_workspace(db, working_dir)
            with pytest.raises(SessionExtractorError) as exc_info:
                extract_session_transcript(ws_id, db)
        finally:
            db.close()

        assert exc_info.value.code == "no_session_found"

    def test_extract_raises_not_found_for_unknown_workspace_id(self, clean_db, fake_home):
        from core.db import get_db

        db = get_db()
        try:
            with pytest.raises(SessionExtractorError) as exc_info:
                extract_session_transcript(99999, db)
        finally:
            db.close()

        assert exc_info.value.code == "not_found"
