"""Unit tests for services/annotation_anchor.py (pure re-anchoring logic)."""
from services.annotation_anchor import (
    SEARCH_RADIUS_LINES,
    AnchorPosition,
    capture_anchor,
    is_valid_range,
    resolve_anchor,
    split_lines,
)


def _numbered_lines(count: int) -> list[str]:
    return [f"line {number}" for number in range(1, count + 1)]


class TestSplitLines:
    def test_split_lines_should_return_empty_list_when_content_empty(self):
        assert split_lines("") == []

    def test_split_lines_should_drop_trailing_newline_when_content_ends_with_newline(self):
        assert split_lines("a\nb\n") == ["a", "b"]

    def test_split_lines_should_normalize_crlf_when_content_uses_windows_line_endings(self):
        assert split_lines("a\r\nb\r\n") == ["a", "b"]

    def test_split_lines_should_keep_inner_blank_lines_when_file_has_empty_lines(self):
        assert split_lines("a\n\nb") == ["a", "", "b"]


class TestCaptureAndValidRange:
    def test_capture_anchor_should_join_inclusive_range_when_multiple_lines(self):
        assert capture_anchor(["a", "b", "c", "d"], 2, 3) == "b\nc"

    def test_is_valid_range_should_accept_whole_file_when_range_covers_all_lines(self):
        assert is_valid_range(["a", "b"], 1, 2) is True

    def test_is_valid_range_should_reject_when_start_is_zero(self):
        assert is_valid_range(["a", "b"], 0, 1) is False

    def test_is_valid_range_should_reject_when_end_before_start(self):
        assert is_valid_range(["a", "b"], 2, 1) is False

    def test_is_valid_range_should_reject_when_end_past_file_end(self):
        assert is_valid_range(["a", "b"], 1, 3) is False


class TestResolveAnchor:
    def test_resolve_anchor_should_keep_stored_lines_when_content_unchanged(self):
        lines = ["a", "b", "c"]

        position = resolve_anchor(lines, 2, 2, "b")

        assert position == AnchorPosition(2, 2, False)

    def test_resolve_anchor_should_shift_down_when_lines_inserted_above(self):
        lines = ["new 1", "new 2", "new 3", "a", "b", "c"]

        position = resolve_anchor(lines, 2, 2, "b")

        assert position == AnchorPosition(5, 5, False)

    def test_resolve_anchor_should_shift_up_when_lines_deleted_above(self):
        lines = ["c", "target", "d"]

        position = resolve_anchor(lines, 5, 5, "target")

        assert position == AnchorPosition(2, 2, False)

    def test_resolve_anchor_should_move_whole_range_when_multi_line_anchor_shifted(self):
        lines = ["inserted", "a", "def f():", "    return 1", "z"]

        position = resolve_anchor(lines, 2, 3, "def f():\n    return 1")

        assert position == AnchorPosition(3, 4, False)

    def test_resolve_anchor_should_not_match_partially_when_only_first_anchor_line_survives(self):
        lines = ["def f():", "    return 2", "x"]

        position = resolve_anchor(lines, 1, 2, "def f():\n    return 1")

        assert position.stale is True

    def test_resolve_anchor_should_match_trimmed_when_only_indentation_changed(self):
        lines = ["class A:", "    if x:", "        return 1"]

        position = resolve_anchor(lines, 1, 2, "if x:\n    return 1")

        assert position == AnchorPosition(2, 3, False)

    def test_resolve_anchor_should_prefer_exact_match_when_trimmed_match_is_closer(self):
        lines = ["  value = 1", "x", "x", "value = 1"]

        position = resolve_anchor(lines, 1, 1, "value = 1")

        assert position == AnchorPosition(4, 4, False)

    def test_resolve_anchor_should_pick_nearest_copy_when_anchor_text_duplicated(self):
        lines = ["dup", "a", "b", "c", "d", "e", "f", "dup", "g"]

        position = resolve_anchor(lines, 6, 6, "dup")

        assert position == AnchorPosition(8, 8, False)

    def test_resolve_anchor_should_prefer_copy_above_when_duplicates_equidistant(self):
        lines = ["dup", "x", "y", "dup"]

        position = resolve_anchor(lines, 2, 2, "dup")

        assert position == AnchorPosition(1, 1, False)

    def test_resolve_anchor_should_mark_stale_at_stored_lines_when_anchor_removed(self):
        lines = ["a", "b", "c", "d", "e"]

        position = resolve_anchor(lines, 2, 3, "gone\nalso gone")

        assert position == AnchorPosition(2, 3, True)

    def test_resolve_anchor_should_clamp_to_file_length_when_stale_range_past_end(self):
        lines = ["a", "b", "c"]

        position = resolve_anchor(lines, 2, 10, "gone")

        assert position == AnchorPosition(2, 3, True)

    def test_resolve_anchor_should_clamp_start_and_end_when_file_shorter_than_stored_start(self):
        lines = ["a", "b"]

        position = resolve_anchor(lines, 7, 9, "gone")

        assert position == AnchorPosition(2, 2, True)

    def test_resolve_anchor_should_stale_at_line_one_when_file_empty(self):
        position = resolve_anchor([], 4, 6, "gone")

        assert position == AnchorPosition(1, 1, True)

    def test_resolve_anchor_should_find_anchor_when_file_shorter_than_stored_range(self):
        lines = ["target", "x"]

        position = resolve_anchor(lines, 10, 10, "target")

        assert position == AnchorPosition(1, 1, False)

    def test_resolve_anchor_should_find_match_when_exactly_at_search_radius(self):
        lines = _numbered_lines(400)
        lines[1 + SEARCH_RADIUS_LINES - 1] = "anchor"

        position = resolve_anchor(lines, 1, 1, "anchor")

        assert position == AnchorPosition(1 + SEARCH_RADIUS_LINES, 1 + SEARCH_RADIUS_LINES, False)

    def test_resolve_anchor_should_mark_stale_when_match_one_line_beyond_search_radius(self):
        lines = _numbered_lines(400)
        lines[1 + SEARCH_RADIUS_LINES] = "anchor"

        position = resolve_anchor(lines, 1, 1, "anchor")

        assert position == AnchorPosition(1, 1, True)

    def test_resolve_anchor_should_find_match_above_when_exactly_at_search_radius_below_origin(self):
        lines = _numbered_lines(400)
        lines[0] = "anchor"
        origin = 1 + SEARCH_RADIUS_LINES

        position = resolve_anchor(lines, origin, origin, "anchor")

        assert position == AnchorPosition(1, 1, False)
