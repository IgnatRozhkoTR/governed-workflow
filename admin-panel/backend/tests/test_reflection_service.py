"""Tests for reflection_service: run, get, list_reflections."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from core.llm_client import LLMClientError
from services import reflection_service
from services.reflection_service import ReflectionServiceError
from services.session_extractor import SessionExtractorError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_TRANSCRIPT = {
    "session_id": "sess-abc",
    "transcript": "User: hello\nAssistant: hi",
    "message_count": 2,
    "started_at": "2024-01-01T10:00:00",
}

_LLM_REPORT_MD = (
    "## What was done\nImplemented feature X.\n"
    "## What worked\nTests passed.\n"
    "## What did not work\nNothing major.\n"
    "## Lessons\nStart simple."
)

_LLM_JSON_RESPONSE = (
    '{"report_md": "' + _LLM_REPORT_MD.replace('"', '\\"').replace("\n", "\\n") + '",'
    ' "summary": "Feature X delivered cleanly.", "proposals": []}'
)


def _make_workspace(db) -> int:
    db.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        ("test-project", "Test Project", "/tmp/test", "2024-01-01"),
    )
    cursor = db.execute(
        "INSERT INTO workspaces "
        "(project_id, branch, sanitized_branch, working_dir, created, status, phase, scope_json, plan_json, source_branch) "
        "VALUES ('test-project', 'feature/x', 'feature-x', '/tmp/test', '2024-01-01', 'active', '0', '{}', '{}', 'main')"
    )
    ws_id = cursor.lastrowid
    db.commit()
    return ws_id


# ---------------------------------------------------------------------------
# run() tests
# ---------------------------------------------------------------------------

class TestReflectionServiceRun:
    def test_run_persists_row_and_returns_dict(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch("services.reflection_service.session_extractor.extract_session_transcript", return_value=_FAKE_TRANSCRIPT),
                patch("services.reflection_service.llm_client.complete", return_value=_LLM_JSON_RESPONSE),
            ):
                result = reflection_service.run(db, ws_id)
        finally:
            db.close()

        assert result["id"] is not None
        assert result["workspace_id"] == ws_id
        assert result["session_id"] == "sess-abc"
        assert "content_md" in result
        assert "summary" in result
        assert "created_at" in result

        db = get_db()
        try:
            row = db.execute("SELECT * FROM reflections WHERE id = ?", (result["id"],)).fetchone()
        finally:
            db.close()

        assert row is not None
        assert row["workspace_id"] == ws_id

    def test_run_parses_summary_from_json(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch("services.reflection_service.session_extractor.extract_session_transcript", return_value=_FAKE_TRANSCRIPT),
                patch("services.reflection_service.llm_client.complete", return_value=_LLM_JSON_RESPONSE),
            ):
                result = reflection_service.run(db, ws_id)
        finally:
            db.close()

        assert result["summary"] == "Feature X delivered cleanly."
        assert result["content_md"] == _LLM_REPORT_MD

    def test_run_raises_not_found_for_missing_workspace(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            with pytest.raises(ReflectionServiceError) as exc_info:
                reflection_service.run(db, 99999)
        finally:
            db.close()

        assert exc_info.value.code == "not_found"

    def test_run_raises_no_session_found_when_extractor_does(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with patch(
                "services.reflection_service.session_extractor.extract_session_transcript",
                side_effect=SessionExtractorError("no JSONL", code="no_session_found"),
            ):
                with pytest.raises(ReflectionServiceError) as exc_info:
                    reflection_service.run(db, ws_id)
        finally:
            db.close()

        assert exc_info.value.code == "no_session_found"

    def test_run_raises_llm_unconfigured_when_env_missing(self, clean_db, monkeypatch):
        from core.db import get_db

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with patch(
                "services.reflection_service.session_extractor.extract_session_transcript",
                return_value=_FAKE_TRANSCRIPT,
            ):
                with pytest.raises(ReflectionServiceError) as exc_info:
                    reflection_service.run(db, ws_id)
        finally:
            db.close()

        assert exc_info.value.code == "llm_unconfigured"

    def test_run_raises_llm_failure_on_api_error(self, clean_db, monkeypatch):
        from core.db import get_db

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch(
                    "services.reflection_service.session_extractor.extract_session_transcript",
                    return_value=_FAKE_TRANSCRIPT,
                ),
                patch(
                    "services.reflection_service.llm_client.complete",
                    side_effect=LLMClientError("connection reset", code="api_error"),
                ),
            ):
                with pytest.raises(ReflectionServiceError) as exc_info:
                    reflection_service.run(db, ws_id)
        finally:
            db.close()

        assert exc_info.value.code == "llm_failure"

    def test_run_v2_emits_proposals_for_each_valid_proposal(self, clean_db):
        import json
        from core.db import get_db

        llm_json = json.dumps({
            "report_md": "## Report\nSome content.",
            "summary": "Two proposals emitted.",
            "proposals": [
                {
                    "type": "memory_write",
                    "title": "Save context note",
                    "body": "Remember this approach.",
                    "payload": {"content": "important note"},
                },
                {
                    "type": "workflow_improvement",
                    "title": "Add reflection step",
                    "body": "Always reflect after finalization.",
                    "payload": {},
                },
            ],
        })

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch("services.reflection_service.session_extractor.extract_session_transcript", return_value=_FAKE_TRANSCRIPT),
                patch("services.reflection_service.llm_client.complete", return_value=llm_json),
            ):
                result = reflection_service.run(db, ws_id)

            proposals = db.execute(
                "SELECT * FROM proposals WHERE origin = 'reflection' ORDER BY id",
            ).fetchall()
        finally:
            db.close()

        assert len(proposals) == 2
        assert proposals[0]["type"] == "memory_write"
        assert proposals[1]["type"] == "workflow_improvement"
        assert all(p["origin"] == "reflection" for p in proposals)
        assert all(p["project_id"] is not None for p in proposals)

    def test_run_v2_returns_proposal_ids_in_result(self, clean_db):
        import json
        from core.db import get_db

        llm_json = json.dumps({
            "report_md": "## Report\nDone.",
            "summary": "Single proposal.",
            "proposals": [
                {
                    "type": "rule_new",
                    "title": "New lint rule",
                    "body": "Enforce style.",
                    "payload": {},
                },
            ],
        })

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch("services.reflection_service.session_extractor.extract_session_transcript", return_value=_FAKE_TRANSCRIPT),
                patch("services.reflection_service.llm_client.complete", return_value=llm_json),
            ):
                result = reflection_service.run(db, ws_id)
        finally:
            db.close()

        assert "proposal_ids" in result
        assert isinstance(result["proposal_ids"], list)
        assert len(result["proposal_ids"]) == 1
        assert isinstance(result["proposal_ids"][0], int)

    def test_run_v2_skips_invalid_proposal_types_and_logs(self, clean_db, capsys):
        import json
        from core.db import get_db

        llm_json = json.dumps({
            "report_md": "## Report",
            "summary": "Mixed proposals.",
            "proposals": [
                {
                    "type": "foobar",
                    "title": "Bad type",
                    "body": "Should be skipped.",
                    "payload": {},
                },
                {
                    "type": "memory_write",
                    "title": "Valid one",
                    "body": "This should persist.",
                    "payload": {"content": "valid content"},
                },
            ],
        })

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch("services.reflection_service.session_extractor.extract_session_transcript", return_value=_FAKE_TRANSCRIPT),
                patch("services.reflection_service.llm_client.complete", return_value=llm_json),
            ):
                result = reflection_service.run(db, ws_id)

            rows = db.execute("SELECT * FROM proposals").fetchall()
        finally:
            db.close()

        assert len(rows) == 1
        assert rows[0]["type"] == "memory_write"
        assert len(result["proposal_ids"]) == 1

        captured = capsys.readouterr()
        assert "foobar" in captured.err or "skipping" in captured.err

    def test_run_v2_raises_llm_invalid_json_on_malformed_json(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch("services.reflection_service.session_extractor.extract_session_transcript", return_value=_FAKE_TRANSCRIPT),
                patch("services.reflection_service.llm_client.complete", return_value='{"report_md": "truncated json'),
            ):
                with pytest.raises(ReflectionServiceError) as exc_info:
                    reflection_service.run(db, ws_id)
        finally:
            db.close()

        assert exc_info.value.code == "llm_invalid_json"

    def test_run_v2_with_empty_proposals_list_succeeds(self, clean_db):
        import json
        from core.db import get_db

        llm_json = json.dumps({
            "report_md": "## Report\nNothing to improve.",
            "summary": "Quiet session.",
            "proposals": [],
        })

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch("services.reflection_service.session_extractor.extract_session_transcript", return_value=_FAKE_TRANSCRIPT),
                patch("services.reflection_service.llm_client.complete", return_value=llm_json),
            ):
                result = reflection_service.run(db, ws_id)

            count = db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        finally:
            db.close()

        assert count == 0
        assert result["proposal_ids"] == []
        assert result["summary"] == "Quiet session."


# ---------------------------------------------------------------------------
# get() tests
# ---------------------------------------------------------------------------

class TestReflectionServiceGet:
    def _insert_reflection(self, db, ws_id: int) -> int:
        cursor = db.execute(
            "INSERT INTO reflections (workspace_id, content_md, summary, session_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ws_id, "## Report\nSome content.", "Short summary.", "sess-xyz", "2024-01-01T10:00:00"),
        )
        db.commit()
        return cursor.lastrowid

    def test_get_returns_row_by_id(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            reflection_id = self._insert_reflection(db, ws_id)
            result = reflection_service.get(db, reflection_id)
        finally:
            db.close()

        assert result["id"] == reflection_id
        assert result["workspace_id"] == ws_id
        assert result["content_md"] == "## Report\nSome content."
        assert result["summary"] == "Short summary."
        assert result["session_id"] == "sess-xyz"

    def test_get_raises_not_found_for_unknown_id(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            with pytest.raises(ReflectionServiceError) as exc_info:
                reflection_service.get(db, 99999)
        finally:
            db.close()

        assert exc_info.value.code == "not_found"


# ---------------------------------------------------------------------------
# list_reflections() tests
# ---------------------------------------------------------------------------

class TestReflectionServiceList:
    def _insert_reflection(self, db, ws_id: int, created_at: str, summary: str = "Summary") -> int:
        cursor = db.execute(
            "INSERT INTO reflections (workspace_id, content_md, summary, session_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ws_id, "Content.", summary, "sess-1", created_at),
        )
        db.commit()
        return cursor.lastrowid

    def test_list_returns_rows_in_desc_order(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            id_older = self._insert_reflection(db, ws_id, "2024-01-01T09:00:00", "Older")
            id_newer = self._insert_reflection(db, ws_id, "2024-01-02T09:00:00", "Newer")
            results = reflection_service.list_reflections(db, ws_id)
        finally:
            db.close()

        assert len(results) == 2
        assert results[0]["id"] == id_newer
        assert results[1]["id"] == id_older

    def test_list_returns_empty_for_workspace_with_no_reflections(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            results = reflection_service.list_reflections(db, ws_id)
        finally:
            db.close()

        assert results == []

    def test_list_raises_not_found_for_missing_workspace(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            with pytest.raises(ReflectionServiceError) as exc_info:
                reflection_service.list_reflections(db, 99999)
        finally:
            db.close()

        assert exc_info.value.code == "not_found"
