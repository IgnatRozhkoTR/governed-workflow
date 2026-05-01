"""End-to-end pipeline: reflection_run → proposals (origin='reflection') → admin approval.

Mocks the LLM and session_extractor since neither is available in CI. The proposal
storage, REST listing, and per-type executor side-effects use the real services.
"""
import json
from unittest.mock import patch

from core.db import get_db
from services import reflection_service


_FAKE_TRANSCRIPT = {
    "session_id": "sess-abc",
    "transcript": "User: hello\nAssistant: hi",
    "message_count": 2,
    "started_at": "2024-01-01T10:00:00",
}


def _llm_response(proposals: list[dict]) -> str:
    return json.dumps(
        {
            "report_md": "## Report\nReflection content.",
            "summary": "Reflection summary.",
            "proposals": proposals,
        }
    )


def test_reflection_run_emits_proposals_visible_in_proposals_list(
    clean_db, project, workspace, client
):
    """Reflection emits proposals; GET /api/proposals?origin=reflection lists them."""
    proposals_payload = [
        {
            "type": "memory_write",
            "title": "Save context",
            "body": "Remember decision X.",
            "payload": {
                "content": "We decided X over Y.",
                "scope": {"kind": "project", "project_id": project["id"]},
            },
        },
        {
            "type": "workflow_improvement",
            "title": "Reflect more often",
            "body": "Add reflection step after every phase.",
            "payload": {
                "title": "Reflect more often",
                "body": "Always reflect after each phase.",
            },
        },
    ]
    llm_json = _llm_response(proposals_payload)

    db = get_db()
    try:
        with (
            patch(
                "services.reflection_service.session_extractor.extract_session_transcript",
                return_value=_FAKE_TRANSCRIPT,
            ),
            patch(
                "services.reflection_service.llm_client.complete",
                return_value=llm_json,
            ),
        ):
            result = reflection_service.run(db, workspace["id"])
    finally:
        db.close()

    assert len(result["proposal_ids"]) == 2

    resp = client.get("/api/proposals?origin=reflection")
    assert resp.status_code == 200
    items = resp.get_json()
    assert len(items) == 2
    types = {item["type"] for item in items}
    assert types == {"memory_write", "workflow_improvement"}
    for item in items:
        assert item["origin"] == "reflection"
        assert item["status"] == "pending"


def test_reflection_proposal_approve_executes_underlying_action(
    clean_db, project, workspace, client
):
    """End-to-end: reflection emits memory_write proposal, admin approves via REST,
    memory_provider.save is called and proposal lands in 'executed'."""
    proposals_payload = [
        {
            "type": "memory_write",
            "title": "Approved by admin",
            "body": "Body text",
            "payload": {
                "content": "approved memory content",
                "scope": {"kind": "project", "project_id": project["id"]},
                "metadata": {"tags": ["from-reflection"]},
            },
        },
    ]
    llm_json = _llm_response(proposals_payload)

    db = get_db()
    try:
        with (
            patch(
                "services.reflection_service.session_extractor.extract_session_transcript",
                return_value=_FAKE_TRANSCRIPT,
            ),
            patch(
                "services.reflection_service.llm_client.complete",
                return_value=llm_json,
            ),
        ):
            result = reflection_service.run(db, workspace["id"])

        assert len(result["proposal_ids"]) == 1
        proposal_id = result["proposal_ids"][0]
    finally:
        db.close()

    save_return = {
        "memory_id": "mem-from-reflection",
        "content": "approved memory content",
    }
    with patch(
        "services.proposal_executor.memory_service.save",
        return_value=save_return,
    ) as mock_save:
        resp = client.post(f"/api/proposals/{proposal_id}/approve")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "executed"
    assert body["result"]["memory_id"] == "mem-from-reflection"

    mock_save.assert_called_once()
    call_args = mock_save.call_args
    assert call_args.args[0] == "approved memory content"
    assert call_args.args[1]["kind"] == "project"


def test_reflection_pipeline_skips_invalid_proposals_persists_valid(
    clean_db, project, workspace, client
):
    """A reflection containing one valid + one invalid proposal still emits the
    valid one and lists it; the invalid one is dropped."""
    proposals_payload = [
        {
            "type": "totally_unknown_type",
            "title": "Bad type",
            "body": "should be skipped",
            "payload": {},
        },
        {
            "type": "memory_write",
            "title": "Valid one",
            "body": "Valid body",
            "payload": {
                "content": "Valid memory",
                "scope": {"kind": "project", "project_id": project["id"]},
            },
        },
    ]
    llm_json = _llm_response(proposals_payload)

    db = get_db()
    try:
        with (
            patch(
                "services.reflection_service.session_extractor.extract_session_transcript",
                return_value=_FAKE_TRANSCRIPT,
            ),
            patch(
                "services.reflection_service.llm_client.complete",
                return_value=llm_json,
            ),
        ):
            result = reflection_service.run(db, workspace["id"])
    finally:
        db.close()

    assert len(result["proposal_ids"]) == 1

    resp = client.get("/api/proposals?origin=reflection")
    assert resp.status_code == 200
    items = resp.get_json()
    assert len(items) == 1
    assert items[0]["type"] == "memory_write"
    assert items[0]["title"] == "Valid one"
