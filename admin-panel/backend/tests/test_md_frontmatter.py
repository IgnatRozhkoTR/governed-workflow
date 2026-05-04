"""Tests for _md_frontmatter: parse_frontmatter and serialize."""
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services._md_frontmatter import FrontmatterError, parse_frontmatter, serialize


class TestParseFrontmatter:
    def test_parse_happyPath_returnsDictAndBody(self):
        text = "---\nname: my-agent\ndescription: Does stuff\n---\n\nBody text here.\n"

        frontmatter, body = parse_frontmatter(text)

        assert frontmatter == {"name": "my-agent", "description": "Does stuff"}
        assert body == "Body text here.\n"

    def test_parse_emptyBody_returnsEmptyString(self):
        text = "---\nname: x\n---\n\n"

        frontmatter, body = parse_frontmatter(text)

        assert frontmatter["name"] == "x"
        assert body == ""

    def test_parse_raises_missingFrontmatter_whenNoSeparator(self):
        text = "Just a plain document.\nNo frontmatter."

        with pytest.raises(FrontmatterError) as exc_info:
            parse_frontmatter(text)

        assert exc_info.value.code == "missing_frontmatter"

    def test_parse_raises_missingFrontmatter_whenNonString(self):
        with pytest.raises(FrontmatterError) as exc_info:
            parse_frontmatter(None)

        assert exc_info.value.code == "missing_frontmatter"

    def test_parse_raises_parseError_whenUnterminatedFrontmatter(self):
        text = "---\nname: x\nno closing fence"

        with pytest.raises(FrontmatterError) as exc_info:
            parse_frontmatter(text)

        assert exc_info.value.code == "parse_error"

    def test_parse_raises_parseError_whenYamlIsNotMapping(self):
        text = "---\n- item1\n- item2\n---\n\nBody\n"

        with pytest.raises(FrontmatterError) as exc_info:
            parse_frontmatter(text)

        assert exc_info.value.code == "parse_error"

    def test_parse_emptyYamlBlock_returnsEmptyDict(self):
        text = "---\n---\n\nBody\n"

        frontmatter, body = parse_frontmatter(text)

        assert frontmatter == {}
        assert body == "Body\n"


class TestSerialize:
    def test_serialize_roundTrip_preservesDictAndBody(self):
        original_fm = {"name": "my-agent", "description": "Does stuff", "model": "sonnet"}
        original_body = "This is the body.\nWith multiple lines.\n"

        serialized = serialize(original_fm, original_body)
        result_fm, result_body = parse_frontmatter(serialized)

        assert result_fm == original_fm
        assert result_body == original_body

    def test_serialize_emptyFrontmatterAndBody_roundTrips(self):
        serialized = serialize({}, "")

        result_fm, result_body = parse_frontmatter(serialized)

        assert result_fm == {}
        assert result_body == ""

    def test_serialize_addsTrailingNewlineToBody(self):
        serialized = serialize({"name": "x"}, "body without newline")

        assert serialized.endswith("\n")
        _, body = parse_frontmatter(serialized)
        assert body == "body without newline\n"

    def test_serialize_producesCanonicalEnvelope(self):
        serialized = serialize({"name": "x"}, "body")

        assert serialized.startswith("---\n")
        parts = serialized.split("---")
        assert len(parts) >= 3
