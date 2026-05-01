"""Tests for proposal_executor: one test per proposal type."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import proposal_executor
from services.proposal_service import ProposalServiceError


def _make_proposal(type_, payload):
    return {"type": type_, "payload": payload}


def _make_db_with_project(project_path):
    db = MagicMock()
    row = MagicMock()
    row.__getitem__ = lambda self, key: project_path if key == "path" else None
    db.execute.return_value.fetchone.return_value = row
    return db


class TestExecuteMemoryWrite:
    def test_memoryWrite_callsMemoryServiceSave(self, clean_db):
        db = MagicMock()
        proposal = _make_proposal(
            "memory_write",
            {"content": "note content", "scope": {"kind": "project"}, "metadata": {"author": "agent"}},
        )
        saved = {"memory_id": "mem-1", "content": "note content"}

        with patch("services.proposal_executor.memory_service.save", return_value=saved) as mock_save:
            result = proposal_executor.execute(db, proposal)

        mock_save.assert_called_once()
        assert result["memory_id"] == "mem-1"

    def test_memoryWrite_wrapsProviderError_asExecutionFailed(self, clean_db):
        from services.memory_provider import MemoryProviderError
        db = MagicMock()
        proposal = _make_proposal("memory_write", {"content": "x"})

        with patch(
            "services.proposal_executor.memory_service.save",
            side_effect=MemoryProviderError(code="provider_unavailable", message="not installed"),
        ):
            with pytest.raises(ProposalServiceError) as exc_info:
                proposal_executor.execute(db, proposal)

        assert exc_info.value.code == "execution_failed"
        assert "underlying_code" in exc_info.value.details


class TestExecuteMemoryDelete:
    def test_memoryDelete_callsMemoryServiceDelete(self, clean_db):
        db = MagicMock()
        proposal = _make_proposal("memory_delete", {"memory_id": "mem-42"})

        with patch("services.proposal_executor.memory_service.delete", return_value=True) as mock_del:
            result = proposal_executor.execute(db, proposal)

        mock_del.assert_called_once_with("mem-42")
        assert result == {"ok": True, "deleted_id": "mem-42"}

    def test_memoryDelete_wrapsProviderError_asExecutionFailed(self, clean_db):
        from services.memory_provider import MemoryProviderError
        db = MagicMock()
        proposal = _make_proposal("memory_delete", {"memory_id": "mem-99"})

        with patch(
            "services.proposal_executor.memory_service.delete",
            side_effect=MemoryProviderError(code="memory_not_found", message="not found"),
        ):
            with pytest.raises(ProposalServiceError) as exc_info:
                proposal_executor.execute(db, proposal)

        assert exc_info.value.code == "execution_failed"


class TestExecuteRuleNew:
    def test_ruleNew_callsRuleServiceCreate(self, project):
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "rule_new",
            {
                "project": project["id"],
                "name": "new-rule",
                "description": "desc",
                "paths": ["**/*.py"],
                "body": "Rule body",
            },
        )
        expected = {"name": "new-rule", "source": "user"}

        with patch("services.proposal_executor.rule_service.create_rule", return_value=expected) as mock_create:
            result = proposal_executor.execute(db, proposal)

        mock_create.assert_called_once()
        assert result["name"] == "new-rule"

    def test_ruleNew_wrapsRuleServiceError_asExecutionFailed(self, project):
        from services.rule_service import RuleServiceError
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "rule_new",
            {"project": project["id"], "name": "already-exists", "description": "d"},
        )

        with patch(
            "services.proposal_executor.rule_service.create_rule",
            side_effect=RuleServiceError("exists", code="already_exists"),
        ):
            with pytest.raises(ProposalServiceError) as exc_info:
                proposal_executor.execute(db, proposal)

        assert exc_info.value.code == "execution_failed"
        assert exc_info.value.details["underlying_code"] == "already_exists"


class TestExecuteRuleUpdate:
    def test_ruleUpdate_callsRuleServiceUpdate(self, project):
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "rule_update",
            {"project": project["id"], "name": "existing-rule", "description": "updated"},
        )
        expected = {"name": "existing-rule", "description": "updated"}

        with patch("services.proposal_executor.rule_service.update_rule", return_value=expected) as mock_update:
            result = proposal_executor.execute(db, proposal)

        mock_update.assert_called_once()
        assert result["description"] == "updated"


class TestExecuteAgentNew:
    def test_agentNew_callsAgentServiceCreate(self, project):
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "agent_new",
            {"project": project["id"], "name": "new-agent", "description": "desc", "body": "agent body"},
        )
        expected = {"name": "new-agent", "source": "user"}

        with patch("services.proposal_executor.agent_service.create_agent", return_value=expected) as mock_create:
            result = proposal_executor.execute(db, proposal)

        mock_create.assert_called_once()
        assert result["name"] == "new-agent"

    def test_agentNew_wrapsAgentServiceError_asExecutionFailed(self, project):
        from services.agent_service import AgentServiceError
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "agent_new",
            {"project": project["id"], "name": "duplicate", "description": "d"},
        )

        with patch(
            "services.proposal_executor.agent_service.create_agent",
            side_effect=AgentServiceError("collision", code="name_collision"),
        ):
            with pytest.raises(ProposalServiceError) as exc_info:
                proposal_executor.execute(db, proposal)

        assert exc_info.value.code == "execution_failed"
        assert exc_info.value.details["underlying_code"] == "name_collision"


class TestExecuteAgentUpdate:
    def test_agentUpdate_callsAgentServiceUpdate(self, project):
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "agent_update",
            {"project": project["id"], "name": "existing-agent", "description": "new desc"},
        )
        expected = {"name": "existing-agent", "description": "new desc"}

        with patch("services.proposal_executor.agent_service.update_agent", return_value=expected) as mock_update:
            result = proposal_executor.execute(db, proposal)

        mock_update.assert_called_once()
        assert result["description"] == "new desc"


class TestExecuteSkillNew:
    def test_skillNew_callsSkillServiceCreate(self, project):
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "skill_new",
            {"project": project["id"], "name": "new-skill", "description": "desc", "body": "skill body"},
        )
        expected = {"name": "new-skill", "source": "user"}

        with patch("services.proposal_executor.skill_service.create_skill", return_value=expected) as mock_create:
            result = proposal_executor.execute(db, proposal)

        mock_create.assert_called_once()
        assert result["name"] == "new-skill"

    def test_skillNew_wrapsSkillServiceError_asExecutionFailed(self, project):
        from services.skill_service import SkillServiceError
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "skill_new",
            {"project": project["id"], "name": "default", "description": "d"},
        )

        with patch(
            "services.proposal_executor.skill_service.create_skill",
            side_effect=SkillServiceError("immutable", code="default_immutable"),
        ):
            with pytest.raises(ProposalServiceError) as exc_info:
                proposal_executor.execute(db, proposal)

        assert exc_info.value.code == "execution_failed"
        assert exc_info.value.details["underlying_code"] == "default_immutable"


class TestExecuteSkillUpdate:
    def test_skillUpdate_callsSkillServiceUpdate(self, project):
        db = _make_db_with_project(project["path"])
        proposal = _make_proposal(
            "skill_update",
            {"project": project["id"], "name": "existing-skill", "description": "updated"},
        )
        expected = {"name": "existing-skill", "description": "updated"}

        with patch("services.proposal_executor.skill_service.update_skill", return_value=expected) as mock_update:
            result = proposal_executor.execute(db, proposal)

        mock_update.assert_called_once()
        assert result["description"] == "updated"


class TestExecuteWorkflowImprovement:
    def test_workflowImprovement_insertsIntoImprovements(self, clean_db):
        from core.db import get_db
        db = get_db()
        try:
            proposal = _make_proposal(
                "workflow_improvement",
                {"title": "Better approach", "body": "We should do X instead of Y"},
            )

            result = proposal_executor.execute(db, proposal)
        finally:
            db.close()

        assert result.get("ok") is True
        assert result.get("id") is not None

    def test_workflowImprovement_wrapsValueError_asExecutionFailed(self, clean_db):
        db = MagicMock()
        proposal = _make_proposal(
            "workflow_improvement",
            {"title": "title", "body": "body"},
        )

        with patch(
            "services.proposal_executor.improvement_service.report_improvement",
            side_effect=ValueError("bad data"),
        ):
            with pytest.raises(ProposalServiceError) as exc_info:
                proposal_executor.execute(db, proposal)

        assert exc_info.value.code == "execution_failed"


class TestExecuteInvalidType:
    def test_execute_raises_invalidType_forUnknownProposalType(self, clean_db):
        db = MagicMock()
        proposal = {"type": "totally_unknown", "payload": {}}

        with pytest.raises(ProposalServiceError) as exc_info:
            proposal_executor.execute(db, proposal)

        assert exc_info.value.code == "invalid_type"
