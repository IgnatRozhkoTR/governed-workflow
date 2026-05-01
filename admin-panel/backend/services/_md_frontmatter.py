"""Shared YAML frontmatter parser/serializer for Markdown files.

Used by services that manage `<project>/.claude/...` files (agents, skills,
and any future proposal types) to read and write a common
`---\n<yaml>\n---\n\n<body>` envelope. Rule files predate this helper and
keep their own inline parser for now to avoid behavior drift.
"""
from __future__ import annotations

import yaml


_FRONTMATTER_SEPARATOR = "---"


class FrontmatterError(Exception):
    """Domain error raised by frontmatter parsing/serialization."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a Markdown document into (frontmatter_dict, body_text).

    Raises FrontmatterError(code='missing_frontmatter') if the document does
    not start with a `---` fence. Raises FrontmatterError(code='parse_error')
    if the YAML is unterminated, malformed, or not a mapping.
    """
    if not isinstance(text, str) or not text.startswith(_FRONTMATTER_SEPARATOR):
        raise FrontmatterError(
            "Missing YAML frontmatter",
            code="missing_frontmatter",
        )

    lines = text.split("\n")
    if lines[0].strip() != _FRONTMATTER_SEPARATOR:
        raise FrontmatterError(
            "Missing YAML frontmatter",
            code="missing_frontmatter",
        )

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_SEPARATOR:
            end_index = idx
            break
    if end_index is None:
        raise FrontmatterError(
            "Unterminated frontmatter",
            code="parse_error",
        )

    frontmatter_text = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1:])
    if body.startswith("\n"):
        body = body[1:]

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(
            f"Invalid YAML frontmatter: {exc}",
            code="parse_error",
        ) from exc

    if not isinstance(frontmatter, dict):
        raise FrontmatterError(
            "Frontmatter must be a YAML mapping",
            code="parse_error",
        )

    return frontmatter, body


def serialize(frontmatter: dict, body: str) -> str:
    """Serialize a frontmatter dict + body into the canonical envelope."""
    yaml_text = yaml.safe_dump(
        dict(frontmatter or {}),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    body_text = body or ""
    if body_text and not body_text.endswith("\n"):
        body_text += "\n"
    return f"{_FRONTMATTER_SEPARATOR}\n{yaml_text}{_FRONTMATTER_SEPARATOR}\n\n{body_text}"
