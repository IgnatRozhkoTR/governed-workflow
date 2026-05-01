"""Tests for skill_service: CRUD operations and constraint enforcement."""
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import skill_service
from services.skill_service import SkillServiceError, DEFAULT_SKILL_NAMES


def _write_default_skill(project_path, name):
    skill_dir = Path(project_path) / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Default skill {name}\n---\n\n# {name} body\n",
        encoding="utf-8",
    )


class TestListSkills:
    def test_list_returnsEmpty_whenNoSkillsDir(self, project):
        result = skill_service.list_skills(project["path"])

        assert result == []

    def test_list_returnsSkills_whenFoldersExist(self, project):
        skill_service.create_skill(project["path"], "my-skill", "Does things", "body text")

        result = skill_service.list_skills(project["path"])

        assert len(result) == 1
        assert result[0]["name"] == "my-skill"
        assert result[0]["description"] == "Does things"

    def test_list_marksUserSource_forCreatedSkill(self, project):
        skill_service.create_skill(project["path"], "user-skill", "desc", "body")

        result = skill_service.list_skills(project["path"])

        assert result[0]["source"] == "user"

    def test_list_skipsDirectories_withoutSkillMd(self, project):
        skills_dir = Path(project["path"]) / ".claude" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "empty-dir").mkdir()

        result = skill_service.list_skills(project["path"])

        assert result == []

    def test_list_includesErrorField_whenFrontmatterMalformed(self, project):
        skill_dir = Path(project["path"]) / ".claude" / "skills" / "broken"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("no frontmatter here\n", encoding="utf-8")

        result = skill_service.list_skills(project["path"])

        assert any(r["name"] == "broken" and r.get("error") == "invalid_frontmatter" for r in result)


class TestGetSkill:
    def test_get_returnsFrontmatterAndBody(self, project):
        skill_service.create_skill(
            project["path"], "my-skill", "desc text", "Body content",
            args=["--verbose"], user_invocable=True
        )

        result = skill_service.get_skill(project["path"], "my-skill")

        assert result["name"] == "my-skill"
        assert result["description"] == "desc text"
        assert "Body content" in result["body"]
        assert result["args"] == ["--verbose"]
        assert result["user_invocable"] is True

    def test_get_raises_notFound_whenMissing(self, project):
        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.get_skill(project["path"], "nonexistent")

        assert exc_info.value.code == "not_found"


class TestCreateSkill:
    def test_create_makesFolderAndSkillMd(self, project):
        result = skill_service.create_skill(
            project["path"], "new-skill", "My description", "Skill body"
        )

        assert result["name"] == "new-skill"
        assert result["source"] == "user"
        folder = Path(project["path"]) / ".claude" / "skills" / "new-skill"
        assert folder.is_dir()
        skill_file = folder / "SKILL.md"
        assert skill_file.exists()
        text = skill_file.read_text()
        assert text.startswith("---\n")
        assert "name: new-skill" in text
        assert "Skill body" in text

    def test_create_raises_nameCollision_whenFolderAlreadyExists(self, project):
        skill_service.create_skill(project["path"], "my-skill", "d", "b")

        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.create_skill(project["path"], "my-skill", "d2", "b2")

        assert exc_info.value.code == "name_collision"

    def test_create_raises_defaultImmutable_forDefaultName(self, project):
        if not DEFAULT_SKILL_NAMES:
            pytest.skip("No default skill names discovered")
        default_name = next(iter(DEFAULT_SKILL_NAMES))

        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.create_skill(project["path"], default_name, "d", "b")

        assert exc_info.value.code == "default_immutable"

    @pytest.mark.parametrize("bad_name", ["Skill Name", "skill name", "UPPER", "-leading", "has space"])
    def test_create_raises_invalidName_forBadPattern(self, project, bad_name):
        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.create_skill(project["path"], bad_name, "d", "b")

        assert exc_info.value.code == "invalid_name"

    def test_create_raises_directoryCollision_whenPathIsNotDir(self, project):
        skills_dir = Path(project["path"]) / ".claude" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "file-not-dir").write_text("I am a file\n")

        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.create_skill(project["path"], "file-not-dir", "d", "b")

        assert exc_info.value.code == "directory_collision"


class TestUpdateSkill:
    def test_update_mergesFields_andPreservesNoneFields(self, project):
        skill_service.create_skill(
            project["path"], "my-skill", "original desc", "original body", args=["--flag"]
        )

        result = skill_service.update_skill(project["path"], "my-skill", description="updated desc")

        assert result["description"] == "updated desc"
        assert result["args"] == ["--flag"]
        assert "original body" in result["body"]

    def test_update_replacesBody_whenProvided(self, project):
        skill_service.create_skill(project["path"], "my-skill", "desc", "old body")

        result = skill_service.update_skill(project["path"], "my-skill", body="new body")

        assert "new body" in result["body"]
        assert result["description"] == "desc"

    def test_update_raises_notFound_whenMissing(self, project):
        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.update_skill(project["path"], "nonexistent", description="x")

        assert exc_info.value.code == "not_found"

    def test_update_raises_defaultImmutable_forDefaultName(self, project):
        if not DEFAULT_SKILL_NAMES:
            pytest.skip("No default skill names discovered")
        default_name = next(iter(DEFAULT_SKILL_NAMES))
        _write_default_skill(project["path"], default_name)

        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.update_skill(project["path"], default_name, description="new")

        assert exc_info.value.code == "default_immutable"


class TestDeleteSkill:
    def test_delete_removesFolder_forUserSkill(self, project):
        skill_service.create_skill(project["path"], "to-delete", "d", "b")

        result = skill_service.delete_skill(project["path"], "to-delete")

        assert result is True
        folder = Path(project["path"]) / ".claude" / "skills" / "to-delete"
        assert not folder.exists()

    def test_delete_raises_defaultImmutable_forDefaultName(self, project):
        if not DEFAULT_SKILL_NAMES:
            pytest.skip("No default skill names discovered")
        default_name = next(iter(DEFAULT_SKILL_NAMES))
        _write_default_skill(project["path"], default_name)

        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.delete_skill(project["path"], default_name)

        assert exc_info.value.code == "default_immutable"

    def test_delete_raises_notFound_whenMissing(self, project):
        with pytest.raises(SkillServiceError) as exc_info:
            skill_service.delete_skill(project["path"], "nonexistent")

        assert exc_info.value.code == "not_found"
