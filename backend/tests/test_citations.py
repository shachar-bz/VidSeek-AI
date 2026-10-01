"""Tests the citation grammar and the filter that checks each citation of a streamed answer."""

import pytest

from backend.video_agent import citations
from backend.video_agent.tools.get_video_outline.result import ChapterOutline, VideoOutline

RETRIEVED = [(730.0, 760.0), (3600.0, 3720.0)]


def test_minute_and_hour_timestamps_both_name_a_second() -> None:
    assert citations.seconds_of("12:14") == 734.0
    assert citations.seconds_of("1:23:45") == 5025.0


def test_spans_are_read_out_of_a_nested_tool_result() -> None:
    outline = VideoOutline(
        chapters=[
            ChapterOutline(
                chapter_id="one",
                chapter_index=0,
                title="Opening",
                summary="How it starts.",
                start_seconds=0.0,
                end_seconds=95.5,
            ),
            ChapterOutline(
                chapter_id="two",
                chapter_index=1,
                title="Method",
                summary="How it works.",
                start_seconds=95.5,
                end_seconds=400.0,
            ),
        ]
    )

    assert citations.spans_of(outline) == [(0.0, 95.5), (95.5, 400.0)]


def _filtered(text: str, spans=RETRIEVED, *, size: int | None = None) -> str:
    """The answer as the reader gets it, written whole or `size` characters at a time."""

    stream = citations.CitationFilter(spans)
    pieces = [text] if size is None else [text[i : i + size] for i in range(0, len(text), size)]
    return "".join(stream.feed(piece) for piece in pieces) + stream.finish()


def test_a_citation_inside_a_retrieved_span_is_kept() -> None:
    assert _filtered("The model is used last. [12:14]") == "The model is used last. [12:14]"


def test_a_timestamp_no_tool_returned_is_dropped_with_the_space_before_it() -> None:
    assert _filtered("Deterministic methods first. [13:05] Then more.") == (
        "Deterministic methods first. Then more."
    )


def test_a_dropped_citation_leaves_the_sentence_ending_intact() -> None:
    assert _filtered("It is used last [13:05].") == "It is used last."


def test_both_ends_of_a_range_must_have_been_retrieved() -> None:
    assert _filtered("Explained here. [12:14–12:37]") == "Explained here. [12:14–12:37]"
    assert _filtered("Explained here. [12:14–14:00]") == "Explained here."


@pytest.mark.parametrize("dash", ["-", "–", "—"])
def test_any_dash_separates_a_range(dash: str) -> None:
    assert _filtered(f"Here. [12:14{dash}12:37]") == f"Here. [12:14{dash}12:37]"


def test_an_hour_long_video_is_cited_with_its_hour() -> None:
    assert _filtered("Much later. [1:00:30]") == "Much later. [1:00:30]"


def test_a_misshapen_timestamp_is_dropped_rather_than_shown() -> None:
    assert _filtered("Somewhere around [12:1].") == "Somewhere around."


def test_brackets_that_were_never_a_timestamp_are_left_alone() -> None:
    assert _filtered("The speaker [the host] explains it.") == "The speaker [the host] explains it."


def test_rounding_a_span_boundary_either_way_is_still_grounded() -> None:
    spans = [(734.6, 757.4)]

    assert _filtered("Either reading. [12:14] [12:15]", spans) == "Either reading. [12:14] [12:15]"


@pytest.mark.parametrize("size", [1, 2, 3, 7])
def test_where_the_stream_breaks_does_not_change_what_is_shown(size: int) -> None:
    text = "Grounded. [12:14–12:37] Invented. [13:05] [the host] Done [12:1]."

    assert _filtered(text, size=size) == _filtered(text) == "Grounded. [12:14–12:37] Invented. [the host] Done."


def test_text_is_shown_as_it_arrives_and_only_the_open_citation_waits() -> None:
    stream = citations.CitationFilter(RETRIEVED)

    assert stream.feed("Used last") == "Used last"
    assert stream.feed(". [12") == "."
    assert stream.feed(":14]") == " [12:14]"
    assert stream.finish() == ""


def test_a_bracket_that_never_closes_is_shown_as_prose_at_the_end() -> None:
    assert _filtered("Ends with an open [12:14") == "Ends with an open [12:14"


def test_a_second_open_bracket_means_the_first_was_not_a_citation() -> None:
    assert _filtered("See [note [12:14] here") == "See [note [12:14] here"


def test_a_bracket_open_for_too_long_is_released_as_prose() -> None:
    stream = citations.CitationFilter(RETRIEVED)
    held = "[" + "x" * (citations.MAX_CITATION_LENGTH - 1)

    assert stream.feed(held) == ""
    assert stream.feed("y") == held + "y"
    assert stream.finish() == ""


def test_retrieved_spans_collect_this_turns_results_after_the_restored_ones() -> None:
    retrieved = citations.RetrievedSpans()
    retrieved.restore([(10.0, 20.0)])
    retrieved.record({"memories": [{"start_seconds": 730.0, "end_seconds": 760.0}]})

    assert retrieved.spans == [(10.0, 20.0), (730.0, 760.0)]
