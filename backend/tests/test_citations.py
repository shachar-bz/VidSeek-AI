"""Tests the citation grammar, the check against retrieved moments, and the stripped fallback."""

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


def test_a_citation_inside_a_retrieved_span_is_accepted() -> None:
    assert citations.unverified("The model is used last. [12:14]", RETRIEVED) == []


def test_a_timestamp_no_tool_returned_is_rejected() -> None:
    assert citations.unverified("Deterministic methods first. [13:05]", RETRIEVED) == ["[13:05]"]


def test_both_ends_of_a_range_must_have_been_retrieved() -> None:
    assert citations.unverified("Explained here. [12:14–12:37]", RETRIEVED) == []
    assert citations.unverified("Explained here. [12:14–14:00]", RETRIEVED) == ["[12:14–14:00]"]


@pytest.mark.parametrize("dash", ["-", "–", "—"])
def test_any_dash_separates_a_range(dash: str) -> None:
    assert citations.unverified(f"Here. [12:14{dash}12:37]", RETRIEVED) == []


def test_an_hour_long_video_is_cited_with_its_hour() -> None:
    assert citations.unverified("Much later. [1:00:30]", RETRIEVED) == []


def test_a_misshapen_timestamp_is_a_violation_rather_than_prose() -> None:
    assert citations.unverified("Somewhere around [12:1].", RETRIEVED) == ["[12:1]"]


def test_brackets_that_were_never_a_timestamp_are_left_alone() -> None:
    assert citations.unverified("The speaker [the host] explains it.", RETRIEVED) == []


def test_rounding_a_span_boundary_either_way_is_still_grounded() -> None:
    spans = [(734.6, 757.4)]

    assert citations.unverified("Either reading. [12:14] [12:15]", spans) == []


def test_stripping_removes_only_what_could_not_be_supported() -> None:
    text = "The model is used last. [12:14] Deterministic methods come first. [13:05]"

    assert citations.strip_unverified(text, RETRIEVED) == (
        "The model is used last. [12:14] Deterministic methods come first."
    )


def test_a_draft_collects_spans_and_hands_back_only_verifiable_text() -> None:
    draft = citations.AnswerDraft()
    draft.record({"memories": [{"start_seconds": 730.0, "end_seconds": 760.0}]})
    draft.text = "Grounded. [12:14] Invented. [13:05]"

    assert draft.verifiable_text() == "Grounded. [12:14] Invented."


