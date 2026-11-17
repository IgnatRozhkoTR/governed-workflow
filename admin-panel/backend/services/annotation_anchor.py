"""Line-anchor capture and re-anchoring for code annotations.

Pure functions over a file's lines (no DB, no git), so both the annotation
service and the review pipeline can resolve where an annotation sits in
whatever version of a file they are looking at.
"""
from typing import Callable, NamedTuple

SEARCH_RADIUS_LINES = 200


class AnchorPosition(NamedTuple):
    line_start: int
    line_end: int
    stale: bool


def split_lines(content: str) -> list[str]:
    """Split file content the way editors number lines: on \\n or \\r\\n only."""
    if not content:
        return []
    lines = content.replace("\r\n", "\n").split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def is_valid_range(lines: list[str], line_start: int, line_end: int) -> bool:
    return 1 <= line_start <= line_end <= len(lines)


def capture_anchor(lines: list[str], line_start: int, line_end: int) -> str:
    return "\n".join(lines[line_start - 1:line_end])


def resolve_anchor(lines: list[str], line_start: int, line_end: int, anchor_text: str) -> AnchorPosition:
    """Locate an annotation's anchor in ``lines``.

    Stored position first, then the nearest exact multi-line match, then the
    nearest whitespace-trimmed match within SEARCH_RADIUS_LINES of the stored
    start. When nothing matches the annotation is stale and keeps its stored
    lines clamped to the file length.
    """
    if is_valid_range(lines, line_start, line_end) and capture_anchor(lines, line_start, line_end) == anchor_text:
        return AnchorPosition(line_start, line_end, False)

    anchor_lines = anchor_text.split("\n")
    for normalize in (_identity, str.strip):
        match_start = _nearest_match(lines, anchor_lines, line_start, normalize)
        if match_start is not None:
            return AnchorPosition(match_start, match_start + len(anchor_lines) - 1, False)

    return _clamped_stale_position(lines, line_start, line_end)


def _identity(line: str) -> str:
    return line


def _nearest_match(
    lines: list[str], anchor_lines: list[str], origin: int, normalize: Callable[[str], str]
) -> int | None:
    normalized_anchor = [normalize(line) for line in anchor_lines]
    last_possible_start = len(lines) - len(anchor_lines) + 1
    for offset in range(SEARCH_RADIUS_LINES + 1):
        for candidate in _candidates_at_offset(origin, offset):
            if 1 <= candidate <= last_possible_start and _matches_at(lines, normalized_anchor, candidate, normalize):
                return candidate
    return None


def _candidates_at_offset(origin: int, offset: int) -> tuple[int, ...]:
    if offset == 0:
        return (origin,)
    return (origin - offset, origin + offset)


def _matches_at(lines: list[str], normalized_anchor: list[str], start: int, normalize: Callable[[str], str]) -> bool:
    for index, expected in enumerate(normalized_anchor):
        if normalize(lines[start - 1 + index]) != expected:
            return False
    return True


def _clamped_stale_position(lines: list[str], line_start: int, line_end: int) -> AnchorPosition:
    last_line = max(len(lines), 1)
    clamped_start = min(line_start, last_line)
    clamped_end = max(clamped_start, min(line_end, last_line))
    return AnchorPosition(clamped_start, clamped_end, True)
