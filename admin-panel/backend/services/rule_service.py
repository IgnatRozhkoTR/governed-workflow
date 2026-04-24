"""Rule file management under <project>/.claude/rules/."""
import re
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_RULE_NAMES = frozenset({
    "coding-standards",
    "java-conventions",
    "research-principles",
    "test-standards",
    "validation-pipeline",
})

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,62}$")
_FRONTMATTER_SEPARATOR = "---"


class RuleServiceError(Exception):
    """Domain error for rule service operations."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _rules_dir(project_path) -> Path:
    return Path(project_path) / ".claude" / "rules"


def _rule_path(project_path, name: str) -> Path:
    return _rules_dir(project_path) / f"{name}.md"


def _source_for(name: str) -> str:
    return "default" if name in DEFAULT_RULE_NAMES else "user"


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise RuleServiceError(
            f"Invalid rule name '{name}'. Allowed: lowercase letters, digits, '-', '_', starting with [a-z0-9].",
            code="invalid_name",
        )


def _parse_rule_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith(_FRONTMATTER_SEPARATOR):
        raise RuleServiceError(
            f"Missing YAML frontmatter in {path.name}",
            code="invalid_frontmatter",
        )

    lines = text.split("\n")
    if lines[0].strip() != _FRONTMATTER_SEPARATOR:
        raise RuleServiceError(
            f"Missing YAML frontmatter in {path.name}",
            code="invalid_frontmatter",
        )

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_SEPARATOR:
            end_index = idx
            break
    if end_index is None:
        raise RuleServiceError(
            f"Unterminated frontmatter in {path.name}",
            code="invalid_frontmatter",
        )

    frontmatter_text = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1:])
    if body.startswith("\n"):
        body = body[1:]

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise RuleServiceError(
            f"Invalid YAML frontmatter in {path.name}: {exc}",
            code="invalid_frontmatter",
        ) from exc

    if not isinstance(frontmatter, dict):
        raise RuleServiceError(
            f"Frontmatter must be a mapping in {path.name}",
            code="invalid_frontmatter",
        )

    paths = frontmatter.get("paths") or []
    if not isinstance(paths, list):
        raise RuleServiceError(
            f"'paths' must be a list in {path.name}",
            code="invalid_frontmatter",
        )

    return {
        "name": frontmatter.get("name") or path.stem,
        "description": frontmatter.get("description") or "",
        "paths": [str(p) for p in paths],
        "body": body,
    }


def _serialize_rule(name: str, description: str, paths: list, body: str) -> str:
    frontmatter = {
        "name": name,
        "description": description or "",
        "paths": list(paths or []),
    }
    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    body_text = body or ""
    if body_text and not body_text.endswith("\n"):
        body_text += "\n"
    return f"{_FRONTMATTER_SEPARATOR}\n{yaml_text}{_FRONTMATTER_SEPARATOR}\n\n{body_text}"


def list_rules(project_path) -> list[dict]:
    """Return metadata for every rule in <project>/.claude/rules/.

    Only direct *.md files in the rules directory are considered; files that
    live elsewhere under .claude/ (Git Rules, Task Context) are not rules and
    are not reached by this glob.  Malformed files are included with an
    'error' field instead of raising.
    """
    directory = _rules_dir(project_path)
    if not directory.exists():
        return []

    results = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".md":
            continue
        name = path.stem
        source = _source_for(name)
        try:
            parsed = _parse_rule_file(path)
            results.append({
                "name": name,
                "description": parsed["description"],
                "paths": parsed["paths"],
                "source": source,
            })
        except RuleServiceError as exc:
            results.append({
                "name": name,
                "description": "",
                "paths": [],
                "source": source,
                "error": exc.code,
            })
    return results


def get_rule(project_path, name: str) -> dict:
    """Return full rule content including body."""
    _validate_name(name)
    path = _rule_path(project_path, name)
    if not path.exists():
        raise RuleServiceError(f"Rule '{name}' not found", code="not_found")
    parsed = _parse_rule_file(path)
    return {
        "name": name,
        "description": parsed["description"],
        "paths": parsed["paths"],
        "body": parsed["body"],
        "source": _source_for(name),
    }


def create_rule(project_path, name: str, description: str, paths: list, body: str) -> dict:
    """Create a new user rule. Fails if the name is a default or already exists."""
    _validate_name(name)
    if name in DEFAULT_RULE_NAMES:
        raise RuleServiceError(
            f"Rule '{name}' is a default rule and cannot be created via this API.",
            code="default_immutable",
        )

    directory = _rules_dir(project_path)
    directory.mkdir(parents=True, exist_ok=True)
    path = _rule_path(project_path, name)
    if path.exists():
        raise RuleServiceError(
            f"Rule '{name}' already exists",
            code="already_exists",
        )

    resolved_paths = list(paths or [])
    path.write_text(
        _serialize_rule(name, description or "", resolved_paths, body or ""),
        encoding="utf-8",
    )
    return {
        "name": name,
        "description": description or "",
        "paths": resolved_paths,
        "body": body or "",
        "source": "user",
    }


def update_rule(
    project_path,
    name: str,
    description: Optional[str] = None,
    paths: Optional[list] = None,
    body: Optional[str] = None,
) -> dict:
    """Update an existing user rule. None fields are preserved."""
    _validate_name(name)
    if name in DEFAULT_RULE_NAMES:
        raise RuleServiceError(
            f"Rule '{name}' is a default rule and cannot be modified.",
            code="default_immutable",
        )

    path = _rule_path(project_path, name)
    if not path.exists():
        raise RuleServiceError(f"Rule '{name}' not found", code="not_found")

    existing = _parse_rule_file(path)
    new_description = existing["description"] if description is None else description
    new_paths = existing["paths"] if paths is None else list(paths)
    new_body = existing["body"] if body is None else body

    path.write_text(
        _serialize_rule(name, new_description, new_paths, new_body),
        encoding="utf-8",
    )
    return {
        "name": name,
        "description": new_description,
        "paths": new_paths,
        "body": new_body,
        "source": "user",
    }


def delete_rule(project_path, name: str) -> bool:
    """Delete a user rule. Raises default_immutable for defaults and not_found if missing."""
    _validate_name(name)
    if name in DEFAULT_RULE_NAMES:
        raise RuleServiceError(
            f"Rule '{name}' is a default rule and cannot be deleted.",
            code="default_immutable",
        )

    path = _rule_path(project_path, name)
    if not path.exists():
        raise RuleServiceError(f"Rule '{name}' not found", code="not_found")

    path.unlink()
    return True
