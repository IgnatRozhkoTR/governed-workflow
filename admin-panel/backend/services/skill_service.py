"""Skill folder management under <project>/.claude/skills/."""
import re
import shutil
from pathlib import Path

from services._md_frontmatter import (
    FrontmatterError,
    parse_frontmatter,
    serialize as serialize_frontmatter,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SKILLS_DIR = _REPO_ROOT / "claude" / "skills"
_SKILL_FILE = "SKILL.md"


def _discover_default_skill_names() -> frozenset[str]:
    if not _DEFAULT_SKILLS_DIR.is_dir():
        return frozenset()
    return frozenset(
        path.name
        for path in _DEFAULT_SKILLS_DIR.iterdir()
        if path.is_dir() and (path / _SKILL_FILE).is_file()
    )


DEFAULT_SKILL_NAMES = _discover_default_skill_names()

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,62}$")


class SkillServiceError(Exception):
    """Domain error for skill service operations."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _skills_dir(project_path) -> Path:
    return Path(project_path) / ".claude" / "skills"


def _skill_dir(project_path, name: str) -> Path:
    return _skills_dir(project_path) / name


def _skill_file_path(project_path, name: str) -> Path:
    return _skill_dir(project_path, name) / _SKILL_FILE


def _source_for(name: str) -> str:
    return "default" if name in DEFAULT_SKILL_NAMES else "user"


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise SkillServiceError(
            f"Invalid skill name '{name}'. Allowed: lowercase letters, digits, '-', '_', starting with [a-z0-9].",
            code="invalid_name",
        )


def _parse_skill_file(path: Path) -> dict:
    try:
        frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        raise SkillServiceError(
            f"Invalid frontmatter in {path.parent.name}/{path.name}: {exc}",
            code="invalid_frontmatter",
        ) from exc

    args_value = frontmatter.get("args")
    if args_value is None:
        args = None
    elif isinstance(args_value, list):
        args = [str(item) for item in args_value]
    else:
        raise SkillServiceError(
            f"'args' must be a list in {path.parent.name}/{path.name}",
            code="invalid_frontmatter",
        )

    user_invocable_value = frontmatter.get("user_invocable")
    if user_invocable_value is None:
        user_invocable = None
    elif isinstance(user_invocable_value, bool):
        user_invocable = user_invocable_value
    else:
        raise SkillServiceError(
            f"'user_invocable' must be a boolean in {path.parent.name}/{path.name}",
            code="invalid_frontmatter",
        )

    tools_required_value = frontmatter.get("tools_required")
    if tools_required_value is None:
        tools_required = None
    elif isinstance(tools_required_value, list):
        tools_required = [str(item) for item in tools_required_value]
    else:
        raise SkillServiceError(
            f"'tools_required' must be a list in {path.parent.name}/{path.name}",
            code="invalid_frontmatter",
        )

    return {
        "name": frontmatter.get("name") or path.parent.name,
        "description": frontmatter.get("description") or "",
        "args": args,
        "user_invocable": user_invocable,
        "tools_required": tools_required,
        "body": body,
    }


def _serialize_skill(
    name: str,
    description: str,
    body: str,
    args: list | None,
    user_invocable: bool | None,
    tools_required: list | None,
) -> str:
    frontmatter: dict = {
        "name": name,
        "description": description or "",
    }
    if args is not None:
        frontmatter["args"] = list(args)
    if user_invocable is not None:
        frontmatter["user_invocable"] = bool(user_invocable)
    if tools_required is not None:
        frontmatter["tools_required"] = list(tools_required)
    return serialize_frontmatter(frontmatter, body or "")


def list_skills(project_path) -> list[dict]:
    """Return metadata for every skill in <project>/.claude/skills/.

    Each skill is a directory containing SKILL.md. Directories without
    SKILL.md are skipped. Malformed SKILL.md files are included with an
    'error' field instead of raising.
    """
    directory = _skills_dir(project_path)
    if not directory.exists():
        return []

    results = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / _SKILL_FILE
        if not skill_file.is_file():
            continue
        name = entry.name
        source = _source_for(name)
        try:
            parsed = _parse_skill_file(skill_file)
            results.append({
                "name": name,
                "description": parsed["description"],
                "args": parsed["args"],
                "user_invocable": parsed["user_invocable"],
                "tools_required": parsed["tools_required"],
                "source": source,
            })
        except SkillServiceError as exc:
            results.append({
                "name": name,
                "description": "",
                "args": None,
                "user_invocable": None,
                "tools_required": None,
                "source": source,
                "error": exc.code,
            })
    return results


def get_skill(project_path, name: str) -> dict:
    """Return full skill content including body."""
    _validate_name(name)
    path = _skill_file_path(project_path, name)
    if not path.exists():
        raise SkillServiceError(f"Skill '{name}' not found", code="not_found")
    parsed = _parse_skill_file(path)
    return {
        "name": name,
        "description": parsed["description"],
        "args": parsed["args"],
        "user_invocable": parsed["user_invocable"],
        "tools_required": parsed["tools_required"],
        "body": parsed["body"],
        "source": _source_for(name),
    }


def create_skill(
    project_path,
    name: str,
    description: str,
    body: str,
    args: list | None = None,
    user_invocable: bool | None = None,
    tools_required: list | None = None,
) -> dict:
    """Create a new user skill folder + SKILL.md."""
    _validate_name(name)
    if name in DEFAULT_SKILL_NAMES:
        raise SkillServiceError(
            f"Skill '{name}' is a default skill and cannot be created via this API.",
            code="default_immutable",
        )

    skills_root = _skills_dir(project_path)
    skills_root.mkdir(parents=True, exist_ok=True)
    folder = _skill_dir(project_path, name)
    if folder.exists():
        if folder.is_dir():
            raise SkillServiceError(
                f"Skill '{name}' already exists",
                code="name_collision",
            )
        raise SkillServiceError(
            f"Path '{folder.name}' is not a directory",
            code="directory_collision",
        )

    folder.mkdir(parents=True)
    skill_file = folder / _SKILL_FILE
    skill_file.write_text(
        _serialize_skill(name, description or "", body or "", args, user_invocable, tools_required),
        encoding="utf-8",
    )
    return {
        "name": name,
        "description": description or "",
        "args": list(args) if args is not None else None,
        "user_invocable": user_invocable,
        "tools_required": list(tools_required) if tools_required is not None else None,
        "body": body or "",
        "source": "user",
    }


def update_skill(
    project_path,
    name: str,
    description: str | None = None,
    body: str | None = None,
    args: list | None = None,
    user_invocable: bool | None = None,
    tools_required: list | None = None,
) -> dict:
    """Update an existing user skill. None fields are preserved."""
    _validate_name(name)
    if name in DEFAULT_SKILL_NAMES:
        raise SkillServiceError(
            f"Skill '{name}' is a default skill and cannot be modified.",
            code="default_immutable",
        )

    path = _skill_file_path(project_path, name)
    if not path.exists():
        raise SkillServiceError(f"Skill '{name}' not found", code="not_found")

    existing = _parse_skill_file(path)
    new_description = existing["description"] if description is None else description
    new_body = existing["body"] if body is None else body
    new_args = existing["args"] if args is None else list(args)
    new_user_invocable = existing["user_invocable"] if user_invocable is None else user_invocable
    new_tools_required = existing["tools_required"] if tools_required is None else list(tools_required)

    path.write_text(
        _serialize_skill(
            name,
            new_description,
            new_body,
            new_args,
            new_user_invocable,
            new_tools_required,
        ),
        encoding="utf-8",
    )
    return {
        "name": name,
        "description": new_description,
        "args": new_args,
        "user_invocable": new_user_invocable,
        "tools_required": new_tools_required,
        "body": new_body,
        "source": "user",
    }


def delete_skill(project_path, name: str) -> bool:
    """Delete a user skill folder. Raises default_immutable for defaults and not_found if missing."""
    _validate_name(name)
    if name in DEFAULT_SKILL_NAMES:
        raise SkillServiceError(
            f"Skill '{name}' is a default skill and cannot be deleted.",
            code="default_immutable",
        )

    folder = _skill_dir(project_path, name)
    if not folder.exists():
        raise SkillServiceError(f"Skill '{name}' not found", code="not_found")
    if not folder.is_dir():
        raise SkillServiceError(
            f"Path '{folder.name}' is not a directory",
            code="directory_collision",
        )

    shutil.rmtree(folder)
    return True
