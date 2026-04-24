"""Tests for rule_service, REST endpoints, and MCP rule tools."""
import pytest
from pathlib import Path

from services import rule_service
from services.rule_service import RuleServiceError, DEFAULT_RULE_NAMES


# ── Helpers ──


def _write_default_rule(project_path, name):
    rules_dir = Path(project_path) / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: Default rule {name}\npaths:\n  - '**/*.py'\n---\n\n# {name} body\n",
        encoding="utf-8",
    )


# ── Service-level tests ──


class TestRuleServiceList:
    def test_list_returnsEmpty_whenNoRulesDir(self, project):
        result = rule_service.list_rules(project["path"])
        assert result == []

    def test_list_returnsDefaults_whenDefaultRulesPlaced(self, project):
        for name in DEFAULT_RULE_NAMES:
            _write_default_rule(project["path"], name)
        result = rule_service.list_rules(project["path"])
        names = {r["name"] for r in result}
        assert names == set(DEFAULT_RULE_NAMES)
        for rule in result:
            assert rule["source"] == "default"
            assert rule["paths"] == ["**/*.py"]

    def test_list_mixesDefaultAndUserSources(self, project):
        _write_default_rule(project["path"], "coding-standards")
        rule_service.create_rule(project["path"], "my-rule", "desc", ["**/*.ts"], "body text")
        result = rule_service.list_rules(project["path"])
        by_name = {r["name"]: r for r in result}
        assert by_name["coding-standards"]["source"] == "default"
        assert by_name["my-rule"]["source"] == "user"

    def test_list_includesError_whenFrontmatterMalformed(self, project):
        rules_dir = Path(project["path"]) / ".claude" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
        result = rule_service.list_rules(project["path"])
        assert any(r["name"] == "broken" and r.get("error") == "invalid_frontmatter" for r in result)

    def test_list_rules_excludes_git_rules_file(self, project):
        claude_dir = Path(project["path"]) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "git-rules.md").write_text(
            "Commit often. Push without fear.\n", encoding="utf-8"
        )
        rule_service.create_rule(project["path"], "my-rule", "d", ["**/*.py"], "body")

        result = rule_service.list_rules(project["path"])

        names = {r["name"] for r in result}
        assert "git-rules" not in names
        assert "my-rule" in names

    def test_list_rules_excludes_project_context_file(self, project):
        claude_dir = Path(project["path"]) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "project-context.md").write_text(
            "Some task context notes.\n", encoding="utf-8"
        )
        rule_service.create_rule(project["path"], "my-rule", "d", ["**/*.py"], "body")

        result = rule_service.list_rules(project["path"])

        names = {r["name"] for r in result}
        assert "project-context" not in names
        assert "my-rule" in names


class TestRuleServiceCreate:
    def test_create_succeeds_andMarksSourceUser(self, project):
        result = rule_service.create_rule(
            project["path"], "my-custom", "My custom", ["**/*.md"], "Body text"
        )
        assert result["name"] == "my-custom"
        assert result["source"] == "user"
        assert result["paths"] == ["**/*.md"]

        path = Path(project["path"]) / ".claude" / "rules" / "my-custom.md"
        assert path.exists()
        text = path.read_text()
        assert text.startswith("---\n")
        assert "name: my-custom" in text
        assert "Body text" in text

    def test_create_fails_whenDefaultName(self, project):
        with pytest.raises(RuleServiceError) as exc:
            rule_service.create_rule(
                project["path"], "coding-standards", "x", [], "body"
            )
        assert exc.value.code == "default_immutable"

    def test_create_fails_whenAlreadyExists(self, project):
        rule_service.create_rule(project["path"], "r1", "d", [], "b")
        with pytest.raises(RuleServiceError) as exc:
            rule_service.create_rule(project["path"], "r1", "d", [], "b")
        assert exc.value.code == "already_exists"

    @pytest.mark.parametrize("bad_name", ["../evil", "SPACES", "with space", "-leading", "BadCase", "over" + "x" * 70])
    def test_create_fails_whenInvalidName(self, project, bad_name):
        with pytest.raises(RuleServiceError) as exc:
            rule_service.create_rule(project["path"], bad_name, "d", [], "b")
        assert exc.value.code == "invalid_name"


class TestRuleServiceGet:
    def test_get_returnsBodyAndFrontmatter(self, project):
        rule_service.create_rule(
            project["path"], "my-rule", "desc text", ["src/**/*.py", "tests/**/*.py"], "Main body"
        )
        result = rule_service.get_rule(project["path"], "my-rule")
        assert result["name"] == "my-rule"
        assert result["description"] == "desc text"
        assert result["paths"] == ["src/**/*.py", "tests/**/*.py"]
        assert "Main body" in result["body"]
        assert result["source"] == "user"

    def test_get_fails_whenNotFound(self, project):
        with pytest.raises(RuleServiceError) as exc:
            rule_service.get_rule(project["path"], "missing")
        assert exc.value.code == "not_found"

    def test_get_defaultRule_hasDefaultSource(self, project):
        _write_default_rule(project["path"], "coding-standards")
        result = rule_service.get_rule(project["path"], "coding-standards")
        assert result["source"] == "default"


class TestRuleServiceUpdate:
    def test_update_changesDescriptionOnly(self, project):
        rule_service.create_rule(project["path"], "r1", "old", ["a"], "body")
        result = rule_service.update_rule(project["path"], "r1", description="new")
        assert result["description"] == "new"
        assert result["paths"] == ["a"]
        assert result["body"].rstrip("\n") == "body"

    def test_update_changesPathsOnly(self, project):
        rule_service.create_rule(project["path"], "r1", "d", ["a"], "body")
        result = rule_service.update_rule(project["path"], "r1", paths=["b", "c"])
        assert result["description"] == "d"
        assert result["paths"] == ["b", "c"]
        assert result["body"].rstrip("\n") == "body"

    def test_update_changesBodyOnly(self, project):
        rule_service.create_rule(project["path"], "r1", "d", ["a"], "old")
        result = rule_service.update_rule(project["path"], "r1", body="new body")
        assert result["description"] == "d"
        assert result["paths"] == ["a"]
        assert result["body"].rstrip("\n") == "new body"

    def test_update_fails_whenDefault(self, project):
        _write_default_rule(project["path"], "coding-standards")
        with pytest.raises(RuleServiceError) as exc:
            rule_service.update_rule(project["path"], "coding-standards", description="x")
        assert exc.value.code == "default_immutable"

    def test_update_fails_whenNotFound(self, project):
        with pytest.raises(RuleServiceError) as exc:
            rule_service.update_rule(project["path"], "missing", description="x")
        assert exc.value.code == "not_found"


class TestRuleServiceDelete:
    def test_delete_succeeds_forUserRule(self, project):
        rule_service.create_rule(project["path"], "r1", "d", [], "b")
        assert rule_service.delete_rule(project["path"], "r1") is True
        path = Path(project["path"]) / ".claude" / "rules" / "r1.md"
        assert not path.exists()

    def test_delete_fails_whenDefault(self, project):
        _write_default_rule(project["path"], "java-conventions")
        with pytest.raises(RuleServiceError) as exc:
            rule_service.delete_rule(project["path"], "java-conventions")
        assert exc.value.code == "default_immutable"

    def test_delete_fails_whenNotFound(self, project):
        with pytest.raises(RuleServiceError) as exc:
            rule_service.delete_rule(project["path"], "missing")
        assert exc.value.code == "not_found"


# ── REST endpoint tests ──


class TestRuleEndpoints:
    def test_getList_returnsEmpty(self, client, project):
        response = client.get(f"/api/projects/{project['id']}/rules")
        assert response.status_code == 200
        assert response.get_json() == []

    def test_getList_returnsAllRules(self, client, project):
        _write_default_rule(project["path"], "coding-standards")
        rule_service.create_rule(project["path"], "user-rule", "d", ["**/*.ts"], "body")
        response = client.get(f"/api/projects/{project['id']}/rules")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 2
        names = {r["name"] for r in data}
        assert names == {"coding-standards", "user-rule"}

    def test_getOne_returnsFullRule(self, client, project):
        rule_service.create_rule(project["path"], "one", "desc", ["**/*.py"], "Body")
        response = client.get(f"/api/projects/{project['id']}/rules/one")
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "one"
        assert data["description"] == "desc"
        assert data["body"].startswith("Body")

    def test_getOne_returns404_whenMissing(self, client, project):
        response = client.get(f"/api/projects/{project['id']}/rules/missing")
        assert response.status_code == 404

    def test_post_createsUserRule(self, client, project):
        response = client.post(
            f"/api/projects/{project['id']}/rules",
            json={"name": "new-rule", "description": "d", "paths": ["**/*.go"], "body": "body"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["name"] == "new-rule"
        assert data["source"] == "user"

    def test_post_returns403_forDefaultName(self, client, project):
        response = client.post(
            f"/api/projects/{project['id']}/rules",
            json={"name": "coding-standards", "description": "d", "paths": [], "body": "b"},
        )
        assert response.status_code == 403
        assert response.get_json()["code"] == "default_immutable"

    def test_post_returns409_forDuplicate(self, client, project):
        rule_service.create_rule(project["path"], "dup", "d", [], "b")
        response = client.post(
            f"/api/projects/{project['id']}/rules",
            json={"name": "dup", "description": "d", "paths": [], "body": "b"},
        )
        assert response.status_code == 409

    def test_post_returns400_forInvalidName(self, client, project):
        response = client.post(
            f"/api/projects/{project['id']}/rules",
            json={"name": "../evil", "description": "d", "paths": [], "body": "b"},
        )
        assert response.status_code == 400

    def test_put_updatesFields(self, client, project):
        rule_service.create_rule(project["path"], "r1", "old", ["a"], "body")
        response = client.put(
            f"/api/projects/{project['id']}/rules/r1",
            json={"description": "new", "paths": ["b"]},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["description"] == "new"
        assert data["paths"] == ["b"]
        assert data["body"].rstrip("\n") == "body"

    def test_put_returns403_forDefault(self, client, project):
        _write_default_rule(project["path"], "coding-standards")
        response = client.put(
            f"/api/projects/{project['id']}/rules/coding-standards",
            json={"description": "x"},
        )
        assert response.status_code == 403

    def test_put_returns404_whenMissing(self, client, project):
        response = client.put(
            f"/api/projects/{project['id']}/rules/missing",
            json={"description": "x"},
        )
        assert response.status_code == 404

    def test_delete_removesRule(self, client, project):
        rule_service.create_rule(project["path"], "r1", "d", [], "b")
        response = client.delete(f"/api/projects/{project['id']}/rules/r1")
        assert response.status_code == 200
        path = Path(project["path"]) / ".claude" / "rules" / "r1.md"
        assert not path.exists()

    def test_delete_returns403_forDefault(self, client, project):
        _write_default_rule(project["path"], "coding-standards")
        response = client.delete(f"/api/projects/{project['id']}/rules/coding-standards")
        assert response.status_code == 403

    def test_delete_returns404_whenMissing(self, client, project):
        response = client.delete(f"/api/projects/{project['id']}/rules/missing")
        assert response.status_code == 404

    def test_endpoints_return404_forUnknownProject(self, client):
        response = client.get("/api/projects/nonexistent/rules")
        assert response.status_code == 404


# ── MCP tool tests ──


class TestRuleMcpTools:
    def test_ruleList_returnsEmpty(self, project):
        from mcp_server import rule_list
        result = rule_list(project=project["id"])
        assert result == []

    def test_ruleList_returnsDefaultsAndUsers(self, project):
        _write_default_rule(project["path"], "coding-standards")
        rule_service.create_rule(project["path"], "custom", "d", [], "b")
        from mcp_server import rule_list
        result = rule_list(project=project["id"])
        by_name = {r["name"]: r for r in result}
        assert by_name["coding-standards"]["source"] == "default"
        assert by_name["custom"]["source"] == "user"

    def test_ruleList_errorForUnknownProject(self):
        from mcp_server import rule_list
        result = rule_list(project="no-such-project")
        assert len(result) == 1
        assert result[0]["errorCategory"] == "not_found"

    def test_ruleCreate_happy(self, project):
        from mcp_server import rule_create
        result = rule_create(
            project=project["id"],
            name="fresh",
            description="d",
            paths=["**/*.md"],
            body="Body",
        )
        assert result["name"] == "fresh"
        assert result["source"] == "user"

    def test_ruleCreate_defaultImmutable(self, project):
        from mcp_server import rule_create
        result = rule_create(
            project=project["id"],
            name="coding-standards",
            description="d",
            paths=[],
            body="b",
        )
        assert "error" in result
        assert result["errorCategory"] == "business"

    def test_ruleCreate_invalidName(self, project):
        from mcp_server import rule_create
        result = rule_create(
            project=project["id"],
            name="../evil",
            description="d",
            paths=[],
            body="b",
        )
        assert result["errorCategory"] == "validation"

    def test_ruleDelete_happy(self, project):
        rule_service.create_rule(project["path"], "to-delete", "d", [], "b")
        from mcp_server import rule_delete
        result = rule_delete(project=project["id"], name="to-delete")
        assert result.get("ok") is True
        assert result["deleted_name"] == "to-delete"

    def test_ruleDelete_defaultImmutable(self, project):
        _write_default_rule(project["path"], "test-standards")
        from mcp_server import rule_delete
        result = rule_delete(project=project["id"], name="test-standards")
        assert result["errorCategory"] == "business"

    def test_ruleDelete_notFound(self, project):
        from mcp_server import rule_delete
        result = rule_delete(project=project["id"], name="nothing-here")
        assert result["errorCategory"] == "not_found"

    def test_ruleGet_returnsBody(self, project):
        rule_service.create_rule(project["path"], "r1", "d", ["**/*.py"], "Hello body")
        from mcp_server import rule_get
        result = rule_get(project=project["id"], name="r1")
        assert result["name"] == "r1"
        assert "Hello body" in result["body"]

    def test_ruleUpdate_partial(self, project):
        rule_service.create_rule(project["path"], "r1", "old", ["a"], "body")
        from mcp_server import rule_update
        result = rule_update(project=project["id"], name="r1", description="new")
        assert result["description"] == "new"
        assert result["paths"] == ["a"]
