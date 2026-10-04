"""Tests that bold markers are removed from a streamed answer wherever the stream splits them."""

from backend.video_agent.plain_text import BoldMarkerFilter


def stream(pieces: list[str]) -> str:
    bold_filter = BoldMarkerFilter()
    return "".join(bold_filter.feed(piece) for piece in pieces) + bold_filter.finish()


def test_bold_markers_are_removed_and_the_words_kept() -> None:
    assert stream(["**Custard:** he whisks the eggs. [08:01–09:10]"]) == "Custard: he whisks the eggs. [08:01–09:10]"


def test_a_marker_split_across_pieces_is_still_removed() -> None:
    assert stream(["*", "*Pumpkin pie*", "* filling"]) == "Pumpkin pie filling"


def test_a_lone_asterisk_is_kept_even_at_the_end() -> None:
    assert stream(["* one", "\n* two *"]) == "* one\n* two *"
