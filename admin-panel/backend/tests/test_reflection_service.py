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

_LLM_REPORT = (
    "## What was done\nImplemented feature X.\n"
    "## What worked\nTests passed.\n"
    "## What did not work\nNothing major.\n"
    "## Lessons\nStart simple.\n"
    "\nSUMMARY: Feature X delivered cleanly."
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
                patch("services.reflection_service.llm_client.complete", return_value=_LLM_REPORT),
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

    def test_run_parses_summary_line(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            with (
                patch("services.reflection_service.session_extractor.extract_session_transcript", return_value=_FAKE_TRANSCRIPT),
                patch("services.reflection_service.llm_client.complete", return_value=_LLM_REPORT),
            ):
                result = reflection_service.run(db, ws_id)
        finally:
            db.close()

        assert result["summary"] == "Feature X delivered cleanly."
        assert result["content_md"] == _LLM_REPORT

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
