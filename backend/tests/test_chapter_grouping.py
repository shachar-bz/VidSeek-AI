"""Tests the promise the chapter grouping stage makes about what an LLM can affect.

The stage sends a video's memory summaries to a model and gets a grouping of them back, and
the whole design rests on two claims: the model chooses where the boundaries fall and
nothing else, and it is never shown the transcript. Every timestamp in a finished chapter is
read out of the memories the previous stage produced, and a grouping that does not cover
them exactly once is refused rather than repaired.

These tests hold those claims from both sides. A well-behaved model's answer must produce
chapters whose times match the original memories exactly, and each of the ways a model can
answer badly — an invented ID, a backwards range, an overlap, a gap, a short first or last
chapter — must raise instead of producing chapters that look fine and point at the wrong
part of the video. No test here reaches the network.
"""

import pytest

from backend.semantic_segmentation.chapters import (
    ChapterBoundary,
    ChapterGroupingError,
    MemoryIndex,
    VideoChapterBoundaries,
    VideoChapters,
    chapter_grouping_prompt,
    group_memories,
    request_boundaries,
    validate_boundaries,
)
from backend.semantic_segmentation.memories import VideoMemories, VideoMemory
from backend.services.transcripts import TranscriptSegment

MEMORY_SUMMARIES = [
    ("The speaker explains why many startups fail without validating demand.", 0.0, 40.0),
    ("The speaker describes how their first company made this mistake.", 40.0, 85.0),
    ("The speaker explains how talking to customers changed their process.", 85.0, 130.0),
    ("The speaker turns to hiring, and who to hire first.", 130.0, 180.0),
    ("The speaker describes letting a first hire go.", 180.0, 240.0),
]


def _memories(summaries=MEMORY_SUMMARIES, source="youtube_captions") -> VideoMemories:
    """A video's memories, shaped the way the segmentation stage leaves them."""
    return VideoMemories(
        source=source,
        model="gpt-5.6-sol",
        memories=[
            VideoMemory(
                index=position,
                start_segment_id=f"segment_{position + 1}",
                end_segment_id=f"segment_{position + 1}",
                summary=summary,
                segments=[
                    TranscriptSegment(
                        index=position,
                        start_seconds=start,
                        end_seconds=end,
                        text=f"Spoken words of memory {position + 1}.",
                    )
                ],
            )
            for position, (summary, start, end) in enumerate(summaries)
        ],
    )


def _index(summaries=MEMORY_SUMMARIES) -> MemoryIndex:
    return MemoryIndex(_memories(summaries).memories)


def _boundary(
    start: str, end: str, title: str = "A title.", summary: str = "A summary."
) -> ChapterBoundary:
    return ChapterBoundary(
        start_memory_id=start, end_memory_id=end, title=title, summary=summary
    )


class _FakeResponse:
    def __init__(self, parsed, status="completed"):
        self.output_parsed = parsed
        self.status = status


class _FakeResponses:
    def __init__(self, parsed, status="completed"):
        self._parsed = parsed
        self._status = status
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._parsed, self._status)


class _FakeClient:
    """Stands in for the OpenAI client, answering with a grouping decided by the test."""

    def __init__(self, boundaries=None, status="completed"):
        parsed = VideoChapterBoundaries(chapters=boundaries) if boundaries is not None else None
        self.responses = _FakeResponses(parsed, status)


def test_the_memories_are_sent_with_a_one_based_id_on_every_line() -> None:
    assert _index().render() == (
        "memory_1 [00:00-00:40] The speaker explains why many startups fail without validating demand.\n"
        "memory_2 [00:40-01:25] The speaker describes how their first company made this mistake.\n"
        "memory_3 [01:25-02:10] The speaker explains how talking to customers changed their process.\n"
        "memory_4 [02:10-03:00] The speaker turns to hiring, and who to hire first.\n"
        "memory_5 [03:00-04:00] The speaker describes letting a first hire go."
    )


def test_the_transcript_itself_is_never_sent_to_the_model() -> None:
    memories = _memories()
    client = _FakeClient([_boundary("memory_1", "memory_5")])

    group_memories(memories, client=client)

    sent = client.responses.calls[0]["input"]
    for memory in memories:
        assert memory.summary in sent
        assert memory.transcript not in sent


def test_an_hour_long_video_stamps_every_line_with_hours() -> None:
    index = _index([("One.", 0.0, 40.0), ("Two.", 3600.0, 3700.0)])

    assert index.render().splitlines()[0].startswith("memory_1 [00:00:00-00:00:40]")


def test_the_prompt_is_sent_as_written() -> None:
    prompt = chapter_grouping_prompt()

    assert prompt.startswith("You are given an ordered list of semantic memories from a video.")
    assert (
        "Use only the provided memory IDs and never invent, modify, reorder, or skip memory IDs."
        in prompt
    )
    assert "Chapters must not overlap." in prompt
    assert prompt.endswith(
        "It should describe the overall subject of the chapter rather than simply "
        "repeating or concatenating the individual memory summaries."
    )


def test_chapters_take_their_times_from_the_memories_not_the_model() -> None:
    client = _FakeClient(
        [
            _boundary("memory_1", "memory_3", "Validating demand", "Why startups fail."),
            _boundary("memory_4", "memory_5", "Hiring", "Who to hire, and letting them go."),
        ]
    )

    chapters = group_memories(_memories(), client=client)

    assert isinstance(chapters, VideoChapters)
    assert chapters.source == "youtube_captions"
    assert [chapter.title for chapter in chapters] == ["Validating demand", "Hiring"]

    first, second = chapters.chapters
    assert (first.start_seconds, first.end_seconds) == (0.0, 130.0)
    assert first.memory_count == 3
    assert (second.start_seconds, second.end_seconds) == (130.0, 240.0)
    assert second.memory_count == 2


def test_the_chapters_cover_every_memory_exactly_once() -> None:
    memories = _memories()
    client = _FakeClient(
        [
            _boundary("memory_1", "memory_2"),
            _boundary("memory_3", "memory_3"),
            _boundary("memory_4", "memory_5"),
        ]
    )

    chapters = group_memories(memories, client=client)

    covered = [memory for chapter in chapters for memory in chapter.memories]
    assert covered == memories.memories
    assert chapters.duration_seconds == memories.duration_seconds


def test_the_model_is_given_the_prompt_and_the_numbered_memories() -> None:
    memories = _memories()
    client = _FakeClient([_boundary("memory_1", "memory_5")])

    group_memories(memories, client=client)

    call = client.responses.calls[0]
    assert call["model"] == "gpt-5.6-sol"
    assert call["instructions"] == chapter_grouping_prompt()
    assert call["input"] == MemoryIndex(memories.memories).render()
    assert call["text_format"] is VideoChapterBoundaries


def test_a_video_with_no_memories_is_refused_before_any_request() -> None:
    empty = VideoMemories(source="captions", model="gpt-5.6-sol")
    client = _FakeClient([_boundary("memory_1", "memory_1")])

    with pytest.raises(ChapterGroupingError):
        group_memories(empty, client=client)

    assert client.responses.calls == []


def test_a_response_with_nothing_parsed_is_an_error_rather_than_no_chapters() -> None:
    with pytest.raises(ChapterGroupingError, match="no parsed chapters"):
        request_boundaries(_index(), client=_FakeClient(None, status="incomplete"))


def test_an_invented_memory_id_is_refused() -> None:
    with pytest.raises(ChapterGroupingError, match="does not exist"):
        validate_boundaries(
            [_boundary("memory_1", "memory_4"), _boundary("memory_5", "memory_9")],
            _index(),
        )


def test_a_chapter_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ChapterGroupingError, match="ends before it starts"):
        validate_boundaries([_boundary("memory_5", "memory_1")], _index())


def test_chapters_out_of_chronological_order_are_refused() -> None:
    with pytest.raises(ChapterGroupingError, match="chronological order"):
        validate_boundaries(
            [
                _boundary("memory_1", "memory_3"),
                _boundary("memory_4", "memory_5"),
                _boundary("memory_2", "memory_2"),
            ],
            _index(),
        )


def test_overlapping_chapters_are_refused() -> None:
    with pytest.raises(ChapterGroupingError, match="must not overlap"):
        validate_boundaries(
            [_boundary("memory_1", "memory_3"), _boundary("memory_3", "memory_5")],
            _index(),
        )


def test_a_gap_between_chapters_is_refused() -> None:
    with pytest.raises(ChapterGroupingError, match="memory_3 to memory_4"):
        validate_boundaries(
            [_boundary("memory_1", "memory_2"), _boundary("memory_5", "memory_5")],
            _index(),
        )


def test_chapters_that_do_not_start_at_the_first_memory_are_refused() -> None:
    with pytest.raises(ChapterGroupingError, match="must start at memory_1"):
        validate_boundaries(
            [_boundary("memory_2", "memory_3"), _boundary("memory_4", "memory_5")],
            _index(),
        )


def test_chapters_that_stop_before_the_last_memory_are_refused() -> None:
    with pytest.raises(ChapterGroupingError, match="must end at memory_5"):
        validate_boundaries(
            [_boundary("memory_1", "memory_2"), _boundary("memory_3", "memory_4")],
            _index(),
        )


def test_an_empty_grouping_is_refused() -> None:
    with pytest.raises(ChapterGroupingError, match="no chapters"):
        validate_boundaries([], _index())


def test_a_chapter_serializes_with_its_times_resolved() -> None:
    client = _FakeClient(
        [_boundary("memory_1", "memory_5", "The whole talk", "Startups, from demand to hiring.")]
    )

    payload = group_memories(_memories(), client=client).to_payload()

    assert payload["model"] == "gpt-5.6-sol"
    assert payload["chapter_count"] == 1
    assert payload["chapters"][0] == {
        "index": 0,
        "start_memory_id": "memory_1",
        "end_memory_id": "memory_5",
        "start_seconds": 0.0,
        "end_seconds": 240.0,
        "title": "The whole talk",
        "summary": "Startups, from demand to hiring.",
    }
