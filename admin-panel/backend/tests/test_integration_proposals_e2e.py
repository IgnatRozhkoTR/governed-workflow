"""End-to-end integration tests for the proposal lifecycle (create → approve → execute).

Covers the full pipeline for every proposal type in ``PROPOSAL_TYPES``:
 - memory_write / memory_delete: mock the memory_provider through memory_service.
 - rule_new / rule_update: real on-disk side-effect via ``rule_service``.
 - agent_new / agent_update: real on-disk side-effect via ``agent_service``.
 - skill_new / skill_update: real on-disk side-effect via ``skill_service``.
 - workflow_improvement: real DB insert into ``improvements``.

Plus a failure-path test confirming that an executor exception lands the proposal
in 'failed' with the underlying code/message preserved in result_json.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.db import get_db
from services import proposal_service


# ── helpers ───────────────────────────────────────────────────────────────────


def _create_proposal(db, type_: str, title: str, payload: dict, **extra) -> dict:
    return proposal_service.create(
        db,
        type=type_,
        title=title,
        payload=payload,
        **extra,
    )


def _seed_default_rule_file(project_path: str, name: str) -> Path:
    rules_dir = Path(project_path) / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    file_path = rules_dir / f"{name}.md"
    file_path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: original\n"
        "paths: []\n"
        "---\n\n"
        "Original body\n",
        encoding="utf-8",
    )
    return file_path


def _seed_existing_agent_file(project_path: str, name: str) -> Path:
    agents_dir = Path(project_path) / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    file_path = agents_dir / f"{name}.md"
    file_path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: original\n"
        "model: sonnet\n"
        "---\n\n"
        "Body content\n",
        encoding="utf-8",
    )
    return file_path


def _seed_existing_skill_dir(project_path: str, name: str) -> Path:
    skills_dir = Path(project_path) / ".claude" / "skills" / name
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skills_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        f"name: {name}\n"
        "description: original\n"
        "---\n\n"
        "Body content\n",
        encoding="utf-8",
    )
    return skill_md


# ── memory_write ──────────────────────────────────────────────────────────────


def test_proposal_lifecycle_memory_write_create_approve_execute(clean_db):
    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="memory_write",
            title="Save snippet",
            payload={
                "content": "Important note",
                "scope": {"kind": "project", "project_id": "proj-1"},
                "metadata": {"tags": ["test"]},
            },
        )

        save_return = {"memory_id": "mem-42", "content": "Important note"}
        with patch(
            "services.proposal_executor.memory_service.save",
            return_value=save_return,
        ) as mock_save:
            approved = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert approved["status"] == "executed"
    assert approved["result"]["memory_id"] == "mem-42"
    mock_save.assert_called_once()
    call_args = mock_save.call_args
    assert call_args.args[0] == "Important note"
    assert call_args.args[1] == {"kind": "project", "project_id": "proj-1"}


# ── memory_delete ─────────────────────────────────────────────────────────────


def test_proposal_lifecycle_memory_delete_create_approve_execute(clean_db):
    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="memory_delete",
            title="Forget mem-42",
            payload={"memory_id": "mem-42"},
        )

        with patch(
            "services.proposal_executor.memory_service.delete",
            return_value=True,
        ) as mock_delete:
            approved = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert approved["status"] == "executed"
    assert approved["result"]["deleted_id"] == "mem-42"
    mock_delete.assert_called_once_with("mem-42")


# ── rule_new ──────────────────────────────────────────────────────────────────


def test_proposal_lifecycle_rule_new_create_approve_execute(clean_db, project):
    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="rule_new",
            title="Add new rule",
            payload={
                "project": project["id"],
                "name": "new-test-rule",
                "description": "A rule for tests",
                "paths": ["**/*.py"],
                "body": "Always do X",
            },
        )

        approved = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert approved["status"] == "executed"
    rule_path = Path(project["path"]) / ".claude" / "rules" / "new-test-rule.md"
    assert rule_path.exists()
    contents = rule_path.read_text(encoding="utf-8")
    assert "name: new-test-rule" in contents
    assert "Always do X" in contents


# ── rule_update ───────────────────────────────────────────────────────────────


def test_proposal_lifecycle_rule_update_create_approve_execute(clean_db, project):
    rule_name = "existing-rule"
    rule_path = _seed_default_rule_file(project["path"], rule_name)

    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="rule_update",
            title="Update rule",
            payload={
                "project": project["id"],
                "name": rule_name,
                "description": "updated description",
                "body": "Updated body content",
            },
        )

        approved = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert approved["status"] == "executed"
    contents = rule_path.read_text(encoding="utf-8")
    assert "updated description" in contents
    assert "Updated body content" in contents


# ── agent_new ─────────────────────────────────────────────────────────────────


def test_proposal_lifecycle_agent_new_create_approve_execute(clean_db, project):
    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="agent_new",
            title="Add new agent",
            payload={
                "project": project["id"],
                "name": "researcher-bot",
                "description": "Research agent",
                "body": "You are a researcher.",
                "model": "sonnet",
            },
        )

        approved = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert approved["status"] == "executed"
    agent_path = Path(project["path"]) / ".claude" / "agents" / "researcher-bot.md"
    assert agent_path.exists()
    contents = agent_path.read_text(encoding="utf-8")
    assert "name: researcher-bot" in contents
    assert "You are a researcher." in contents


# ── agent_update ──────────────────────────────────────────────────────────────


def test_proposal_lifecycle_agent_update_create_approve_execute(clean_db, project):
    agent_name = "existing-agent"
    agent_path = _seed_existing_agent_file(project["path"], agent_name)

    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="agent_update",
            title="Tweak agent",
            payload={
                "project": project["id"],
                "name": agent_name,
                "description": "new agent desc",
            },
        )

        approved = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert approved["status"] == "executed"
    contents = agent_path.read_text(encoding="utf-8")
    assert "new agent desc" in contents


# ── skill_new ─────────────────────────────────────────────────────────────────


def test_proposal_lifecycle_skill_new_create_approve_execute(clean_db, project):
    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="skill_new",
            title="Add new skill",
            payload={
                "project": project["id"],
                "name": "test-skill",
                "description": "A skill for testing",
                "body": "Use this skill to test.",
            },
        )

        approved = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert approved["status"] == "executed"
    skill_md = Path(project["path"]) / ".claude" / "skills" / "test-skill" / "SKILL.md"
    assert skill_md.exists()
    contents = skill_md.read_text(encoding="utf-8")
    assert "name: test-skill" in contents
    assert "Use this skill to test." in contents


# ── skill_update ──────────────────────────────────────────────────────────────


def test_proposal_lifecycle_skill_update_create_approve_execute(clean_db, project):
    skill_name = "existing-skill"
    skill_md = _seed_existing_skill_dir(project["path"], skill_name)

    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="skill_update",
            title="Update skill",
            payload={
                "project": project["id"],
                "name": skill_name,
                "description": "modified skill description",
            },
        )

        approved = proposal_service.approve(db, proposal["id"])
    finally:
        db.close()

    assert approved["status"] == "executed"
    contents = skill_md.read_text(encoding="utf-8")
    assert "modified skill description" in contents


# ── workflow_improvement ──────────────────────────────────────────────────────


def test_proposal_lifecycle_workflow_improvement_create_approve_execute(clean_db):
    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="workflow_improvement",
            title="Better approach for X",
            payload={
                "title": "Better approach for X",
                "body": "We should always do Y instead of X.",
            },
        )

        approved = proposal_service.approve(db, proposal["id"])

        improvement_id = approved["result"]["id"]
        row = db.execute(
            "SELECT * FROM improvements WHERE id = ?",
            (improvement_id,),
        ).fetchone()
    finally:
        db.close()

    assert approved["status"] == "executed"
    assert row is not None
    assert row["title"] == "Better approach for X"
    assert row["status"] == "open"


# ── failure path ──────────────────────────────────────────────────────────────


def test_proposal_executor_failure_marks_status_failed_with_result_json(
    clean_db, project
):
    """When the executor raises, the proposal lands in 'failed' and result_json
    carries underlying_code and underlying_message for the operator."""
    db = get_db()
    try:
        proposal = _create_proposal(
            db,
            type_="rule_new",
            title="Will fail",
            payload={
                "project": project["id"],
                "name": "doomed-rule",
                "description": "won't be created",
                "paths": [],
                "body": "x",
            },
        )

        from services.rule_service import RuleServiceError
        with patch(
            "services.proposal_executor.rule_service.create_rule",
            side_effect=RuleServiceError("simulated failure", code="already_exists"),
        ):
            approved = proposal_service.approve(db, proposal["id"])

        row = db.execute(
            "SELECT result_json FROM proposals WHERE id = ?",
            (proposal["id"],),
        ).fetchone()
    finally:
        db.close()

    assert approved["status"] == "failed"
    assert approved["result"] is not None
    assert approved["result"]["underlying_code"] == "already_exists"
    assert "simulated failure" in approved["result"]["underlying_message"]

    persisted_result = json.loads(row["result_json"])
    assert persisted_result["underlying_code"] == "already_exists"
