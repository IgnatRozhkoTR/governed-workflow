"""Agent file management under <project>/.claude/agents/."""
import re
from pathlib import Path

from services._md_frontmatter import (
    FrontmatterError,
    parse_frontmatter,
    serialize as serialize_frontmatter,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_AGENTS_DIR = _REPO_ROOT / "claude" / "agents"


def _discover_default_agent_names() -> frozenset[str]:
    if not _DEFAULT_AGENTS_DIR.is_dir():
        return frozenset()
    return frozenset(
        path.stem
        for path in _DEFAULT_AGENTS_DIR.glob("*.md")
        if path.is_file() and path.stem != "CLAUDE"
    )


DEFAULT_AGENT_NAMES = _discover_default_agent_names()

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,62}$")


class AgentServiceError(Exception):
    """Domain error for agent service operations."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _agents_dir(project_path) -> Path:
    return Path(project_path) / ".claude" / "agents"


def _agent_path(project_path, name: str) -> Path:
    return _agents_dir(project_path) / f"{name}.md"


def _source_for(name: str) -> str:
    return "default" if name in DEFAULT_AGENT_NAMES else "user"


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise AgentServiceError(
            f"Invalid agent name '{name}'. Allowed: lowercase letters, digits, '-', '_', starting with [a-z0-9].",
            code="invalid_name",
        )


def _parse_agent_file(path: Path) -> dict:
    try:
        frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        raise AgentServiceError(
            f"Invalid frontmatter in {path.name}: {exc}",
            code="invalid_frontmatter",
        ) from exc

    tools_value = frontmatter.get("tools")
    if tools_value is None:
        tools = None
    elif isinstance(tools_value, list):
        tools = ", ".join(str(item) for item in tools_value)
    else:
        tools = str(tools_value)

    return {
        "name": frontmatter.get("name") or path.stem,
        "description": frontmatter.get("description") or "",
        "tools": tools,
        "model": frontmatter.get("model"),
        "color": frontmatter.get("color"),
        "body": body,
    }


def _serialize_agent(
    name: str,
    description: str,
    body: str,
    tools: str | None,
    model: str | None,
    color: str | None,
) -> str:
    frontmatter: dict = {
        "name": name,
        "description": description or "",
    }
    if tools is not None:
        frontmatter["tools"] = tools
    if model is not None:
        frontmatter["model"] = model
    if color is not None:
        frontmatter["color"] = color
    return serialize_frontmatter(frontmatter, body or "")


def list_agents(project_path) -> list[dict]:
    """Return metadata for every agent in <project>/.claude/agents/.

    Only direct *.md files in the agents directory are considered. Malformed
    files are included with an 'error' field instead of raising.
    """
    directory = _agents_dir(project_path)
    if not directory.exists():
        return []

    results = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".md":
            continue
        name = path.stem
        if name == "CLAUDE":
            continue
        source = _source_for(name)
        try:
            parsed = _parse_agent_file(path)
            results.append({
                "name": name,
                "description": parsed["description"],
                "tools": parsed["tools"],
                "model": parsed["model"],
                "color": parsed["color"],
                "source": source,
            })
        except AgentServiceError as exc:
            results.append({
                "name": name,
                "description": "",
                "tools": None,
                "model": None,
                "color": None,
                "source": source,
                "error": exc.code,
            })
    return results


def get_agent(project_path, name: str) -> dict:
    """Return full agent content including body."""
    _validate_name(name)
    path = _agent_path(project_path, name)
    if not path.exists():
        raise AgentServiceError(f"Agent '{name}' not found", code="not_found")
    parsed = _parse_agent_file(path)
    return {
        "name": name,
        "description": parsed["description"],
        "tools": parsed["tools"],
        "model": parsed["model"],
        "color": parsed["color"],
        "body": parsed["body"],
        "source": _source_for(name),
    }


def create_agent(
    project_path,
    name: str,
    description: str,
    body: str,
    tools: str | None = None,
    model: str | None = "sonnet",
    color: str | None = None,
) -> dict:
    """Create a new user agent. Fails if the name is a default or already exists."""
    _validate_name(name)
    if name in DEFAULT_AGENT_NAMES:
        raise AgentServiceError(
            f"Agent '{name}' is a default agent and cannot be created via this API.",
            code="default_immutable",
        )

    directory = _agents_dir(project_path)
    directory.mkdir(parents=True, exist_ok=True)
    path = _agent_path(project_path, name)
    if path.exists():
        raise AgentServiceError(
            f"Agent '{name}' already exists",
            code="name_collision",
        )

    path.write_text(
        _serialize_agent(name, description or "", body or "", tools, model, color),
        encoding="utf-8",
    )
    return {
        "name": name,
        "description": description or "",
        "tools": tools,
        "model": model,
        "color": color,
        "body": body or "",
        "source": "user",
    }


def update_agent(
    project_path,
    name: str,
    description: str | None = None,
    body: str | None = None,
    tools: str | None = None,
    model: str | None = None,
    color: str | None = None,
) -> dict:
    """Update an existing user agent. None fields are preserved."""
    _validate_name(name)
    if name in DEFAULT_AGENT_NAMES:
        raise AgentServiceError(
            f"Agent '{name}' is a default agent and cannot be modified.",
            code="default_immutable",
        )

    path = _agent_path(project_path, name)
    if not path.exists():
        raise AgentServiceError(f"Agent '{name}' not found", code="not_found")

    existing = _parse_agent_file(path)
    new_description = existing["description"] if description is None else description
    new_body = existing["body"] if body is None else body
    new_tools = existing["tools"] if tools is None else tools
    new_model = existing["model"] if model is None else model
    new_color = existing["color"] if color is None else color

    path.write_text(
        _serialize_agent(name, new_description, new_body, new_tools, new_model, new_color),
        encoding="utf-8",
    )
    return {
        "name": name,
        "description": new_description,
        "tools": new_tools,
        "model": new_model,
        "color": new_color,
        "body": new_body,
        "source": "user",
    }


def delete_agent(project_path, name: str) -> bool:
    """Delete a user agent. Raises default_immutable for defaults and not_found if missing."""
    _validate_name(name)
    if name in DEFAULT_AGENT_NAMES:
        raise AgentServiceError(
            f"Agent '{name}' is a default agent and cannot be deleted.",
            code="default_immutable",
        )

    path = _agent_path(project_path, name)
    if not path.exists():
        raise AgentServiceError(f"Agent '{name}' not found", code="not_found")

    path.unlink()
    return True
