"""Tests for agent_service: CRUD operations and constraint enforcement."""
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import agent_service
from services.agent_service import AgentServiceError, DEFAULT_AGENT_NAMES


def _write_default_agent(project_path, name):
    agents_dir = Path(project_path) / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: Default agent {name}\n---\n\n# {name} body\n",
        encoding="utf-8",
    )


class TestListAgents:
    def test_list_returnsEmpty_whenNoAgentsDir(self, project):
        result = agent_service.list_agents(project["path"])

        assert result == []

    def test_list_returnsAgents_whenFilesExist(self, project):
        agent_service.create_agent(project["path"], "my-agent", "Does things", "body text")

        result = agent_service.list_agents(project["path"])

        assert len(result) == 1
        assert result[0]["name"] == "my-agent"
        assert result[0]["description"] == "Does things"

    def test_list_marksUserSource_forCreatedAgent(self, project):
        agent_service.create_agent(project["path"], "user-agent", "desc", "body")

        result = agent_service.list_agents(project["path"])

        assert result[0]["source"] == "user"

    def test_list_includesErrorField_whenFrontmatterMalformed(self, project):
        agents_dir = Path(project["path"]) / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")

        result = agent_service.list_agents(project["path"])

        assert any(r["name"] == "broken" and r.get("error") == "invalid_frontmatter" for r in result)


class TestGetAgent:
    def test_get_returnsFrontmatterAndBody(self, project):
        agent_service.create_agent(
            project["path"], "my-agent", "desc text", "Body content", tools="Read,Write", model="sonnet"
        )

        result = agent_service.get_agent(project["path"], "my-agent")

        assert result["name"] == "my-agent"
        assert result["description"] == "desc text"
        assert "Body content" in result["body"]
        assert result["tools"] == "Read,Write"
        assert result["model"] == "sonnet"

    def test_get_raises_notFound_whenMissing(self, project):
        with pytest.raises(AgentServiceError) as exc_info:
            agent_service.get_agent(project["path"], "nonexistent")

        assert exc_info.value.code == "not_found"


class TestCreateAgent:
    def test_create_writesFileWithFrontmatter(self, project):
        result = agent_service.create_agent(
            project["path"], "new-agent", "My description", "Agent body"
        )

        assert result["name"] == "new-agent"
        assert result["source"] == "user"
        path = Path(project["path"]) / ".claude" / "agents" / "new-agent.md"
        assert path.exists()
        text = path.read_text()
        assert text.startswith("---\n")
        assert "name: new-agent" in text
        assert "Agent body" in text

    def test_create_raises_nameCollision_whenAlreadyExists(self, project):
        agent_service.create_agent(project["path"], "my-agent", "d", "b")

        with pytest.raises(AgentServiceError) as exc_info:
            agent_service.create_agent(project["path"], "my-agent", "d2", "b2")

        assert exc_info.value.code == "name_collision"

    def test_create_raises_defaultImmutable_forDefaultName(self, project):
        if not DEFAULT_AGENT_NAMES:
            pytest.skip("No default agent names discovered")
        default_name = next(iter(DEFAULT_AGENT_NAMES))

        with pytest.raises(AgentServiceError) as exc_info:
            agent_service.create_agent(project["path"], default_name, "d", "b")

        assert exc_info.value.code == "default_immutable"

    @pytest.mark.parametrize("bad_name", ["Agent Name", "agent name", "UPPER", "-leading", "has space"])
    def test_create_raises_invalidName_forBadPattern(self, project, bad_name):
        with pytest.raises(AgentServiceError) as exc_info:
            agent_service.create_agent(project["path"], bad_name, "d", "b")

        assert exc_info.value.code == "invalid_name"


class TestUpdateAgent:
    def test_update_mergesFields_andPreservesNoneFields(self, project):
        agent_service.create_agent(
            project["path"], "my-agent", "original desc", "original body", tools="Read"
        )

        result = agent_service.update_agent(project["path"], "my-agent", description="updated desc")

        assert result["description"] == "updated desc"
        assert result["tools"] == "Read"
        assert "original body" in result["body"]

    def test_update_replacesBody_whenProvided(self, project):
        agent_service.create_agent(project["path"], "my-agent", "desc", "old body")

        result = agent_service.update_agent(project["path"], "my-agent", body="new body")

        assert "new body" in result["body"]
        assert result["description"] == "desc"

    def test_update_raises_notFound_whenMissing(self, project):
        with pytest.raises(AgentServiceError) as exc_info:
            agent_service.update_agent(project["path"], "nonexistent", description="x")

        assert exc_info.value.code == "not_found"

    def test_update_raises_defaultImmutable_forDefaultName(self, project):
        if not DEFAULT_AGENT_NAMES:
            pytest.skip("No default agent names discovered")
        default_name = next(iter(DEFAULT_AGENT_NAMES))
        _write_default_agent(project["path"], default_name)

        with pytest.raises(AgentServiceError) as exc_info:
            agent_service.update_agent(project["path"], default_name, description="new")

        assert exc_info.value.code == "default_immutable"


class TestDeleteAgent:
    def test_delete_removesFile_forUserAgent(self, project):
        agent_service.create_agent(project["path"], "to-delete", "d", "b")

        result = agent_service.delete_agent(project["path"], "to-delete")

        assert result is True
        path = Path(project["path"]) / ".claude" / "agents" / "to-delete.md"
        assert not path.exists()

    def test_delete_raises_defaultImmutable_forDefaultName(self, project):
        if not DEFAULT_AGENT_NAMES:
            pytest.skip("No default agent names discovered")
        default_name = next(iter(DEFAULT_AGENT_NAMES))
        _write_default_agent(project["path"], default_name)

        with pytest.raises(AgentServiceError) as exc_info:
            agent_service.delete_agent(project["path"], default_name)

        assert exc_info.value.code == "default_immutable"

    def test_delete_raises_notFound_whenMissing(self, project):
        with pytest.raises(AgentServiceError) as exc_info:
            agent_service.delete_agent(project["path"], "nonexistent")

        assert exc_info.value.code == "not_found"
