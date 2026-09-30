"""Tests the promise the memory segmentation stage makes about what an LLM can affect.

The stage sends a transcript to a model and gets a division of it back, and the whole
design rests on one claim: the model chooses where the boundaries fall and nothing else.
Every timestamp and every word of transcript in a finished memory is read out of the
segments transcription produced, and a division that does not cover the transcript exactly
once is refused rather than repaired.

These tests hold that claim from both sides. A well-behaved model's answer must produce
memories whose text and times match the original transcript exactly, and each of the ways
a model can answer badly — an invented ID, a backwards range, an overlap, a gap, a short
first or last memory — must raise instead of producing memories that look fine and point
at the wrong part of the video. No test here reaches the network.
"""

import pytest

from backend.services.semantic_segmentation.memories import (
    MemoryBoundary,
    MemorySegmentationError,
    SegmentIndex,
    TranscriptMemoryBoundaries,
    VideoMemories,
    memory_segmentation_prompt,
    request_boundaries,
    segment_transcript,
    validate_boundaries,
)
from backend.services.transcripts import (
    NormalizedTranscript,
    TimingFidelity,
    normalize_caption_cues,
)
from backend.services.video_download.youtube.transcript import CaptionSegment

TRANSCRIPT_LINES = [
    ("Today I want to explain why most startups fail.", 0.0, 8.0),
    ("The first reason is that founders build something nobody wants.", 8.0, 17.0),
    ("We made this exact mistake in our first company.", 17.0, 28.0),
    ("Later, we started talking to customers before building.", 28.0, 40.0),
    ("Now let's talk about hiring.", 40.0, 52.0),
]


def _transcript(lines=TRANSCRIPT_LINES):
    """A normalized transcript with one segment per line, built the way the pipeline does."""
    return normalize_caption_cues(
        [CaptionSegment(text=text, start_seconds=start, end_seconds=end) for text, start, end in lines],
        source="youtube_captions",
    )


def _index(lines=TRANSCRIPT_LINES) -> SegmentIndex:
    return SegmentIndex(_transcript(lines).segments)


def _boundary(start: str, end: str, summary: str = "A summary.") -> MemoryBoundary:
    return MemoryBoundary(start_segment_id=start, end_segment_id=end, summary=summary)


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
    """Stands in for the OpenAI client, answering with a division decided by the test."""

    def __init__(self, boundaries=None, status="completed"):
        parsed = (
            TranscriptMemoryBoundaries(memories=boundaries) if boundaries is not None else None
        )
        self.responses = _FakeResponses(parsed, status)


def test_the_transcript_is_sent_with_a_one_based_id_on_every_line() -> None:
    assert _index().render() == (
        "segment_1 [00:00-00:08] Today I want to explain why most startups fail.\n"
        "segment_2 [00:08-00:17] The first reason is that founders build something nobody wants.\n"
        "segment_3 [00:17-00:28] We made this exact mistake in our first company.\n"
        "segment_4 [00:28-00:40] Later, we started talking to customers before building.\n"
        "segment_5 [00:40-00:52] Now let's talk about hiring."
    )


def test_an_hour_long_transcript_stamps_every_line_with_hours() -> None:
    index = _index([("one.", 0.0, 8.0), ("two.", 3600.0, 3608.0)])

    assert index.render().splitlines()[0].startswith("segment_1 [00:00:00-00:00:08]")


def test_the_prompt_is_sent_as_written() -> None:
    prompt = memory_segmentation_prompt()

    assert prompt.startswith("You are given a video transcript with timestamps.")
    assert "Use only the provided segment IDs and never invent, modify, or skip segment IDs." in prompt
    assert (
        "The goal is to create moments that will later be useful for semantic search, "
        "embeddings, and answering user questions about specific parts of the video."
    ) in prompt
    assert prompt.endswith("`summary`: a concise description of what happens or is discussed")


def test_memories_take_their_times_and_text_from_the_transcript_not_the_model() -> None:
    transcript = _transcript()
    client = _FakeClient(
        [
            _boundary("segment_1", "segment_4", "Why startups fail, and the founders' own mistake."),
            _boundary("segment_5", "segment_5", "Turning to hiring."),
        ]
    )

    memories = segment_transcript(transcript, client=client)

    assert isinstance(memories, VideoMemories)
    assert memories.source == "youtube_captions"
    assert [memory.summary for memory in memories] == [
        "Why startups fail, and the founders' own mistake.",
        "Turning to hiring.",
    ]

    first, second = memories.memories
    assert (first.start_seconds, first.end_seconds) == (0.0, 40.0)
    assert first.transcript == " ".join(text for text, _, _ in TRANSCRIPT_LINES[:4])
    assert (second.start_seconds, second.end_seconds) == (40.0, 52.0)
    assert second.transcript == TRANSCRIPT_LINES[4][0]


def test_the_memories_cover_the_whole_transcript_exactly_once() -> None:
    transcript = _transcript()
    client = _FakeClient(
        [
            _boundary("segment_1", "segment_2"),
            _boundary("segment_3", "segment_4"),
            _boundary("segment_5", "segment_5"),
        ]
    )

    memories = segment_transcript(transcript, client=client)

    covered = [segment for memory in memories for segment in memory.segments]
    assert covered == transcript.segments
    assert memories.duration_seconds == transcript.duration_seconds


def test_the_model_is_given_the_prompt_and_the_numbered_transcript() -> None:
    transcript = _transcript()
    client = _FakeClient([_boundary("segment_1", "segment_5")])

    segment_transcript(transcript, client=client)

    call = client.responses.calls[0]
    assert call["model"] == "gpt-6.1-sol"
    assert call["instructions"] == memory_segmentation_prompt()
    assert call["input"] == SegmentIndex(transcript.segments).render()
    assert call["text_format"] is TranscriptMemoryBoundaries


def test_a_transcript_with_no_segments_is_refused_before_any_request() -> None:
    empty = NormalizedTranscript(source="captions", timing_fidelity=TimingFidelity.CAPTION)
    client = _FakeClient([_boundary("segment_1", "segment_1")])

    with pytest.raises(MemorySegmentationError):
        segment_transcript(empty, client=client)

    assert client.responses.calls == []


def test_a_response_with_nothing_parsed_is_an_error_rather_than_no_memories() -> None:
    with pytest.raises(MemorySegmentationError, match="no parsed memories"):
        request_boundaries(_index(), client=_FakeClient(None, status="incomplete"))


def test_an_invented_segment_id_is_refused() -> None:
    with pytest.raises(MemorySegmentationError, match="does not exist"):
        validate_boundaries(
            [_boundary("segment_1", "segment_4"), _boundary("segment_5", "segment_9")],
            _index(),
        )


def test_a_memory_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(MemorySegmentationError, match="ends before it starts"):
        validate_boundaries([_boundary("segment_5", "segment_1")], _index())


def test_memories_out_of_chronological_order_are_refused() -> None:
    with pytest.raises(MemorySegmentationError, match="chronological order"):
        validate_boundaries(
            [
                _boundary("segment_1", "segment_3"),
                _boundary("segment_4", "segment_5"),
                _boundary("segment_2", "segment_2"),
            ],
            _index(),
        )


def test_overlapping_memories_are_refused() -> None:
    with pytest.raises(MemorySegmentationError, match="must not overlap"):
        validate_boundaries(
            [_boundary("segment_1", "segment_3"), _boundary("segment_3", "segment_5")],
            _index(),
        )


def test_a_gap_between_memories_is_refused() -> None:
    with pytest.raises(MemorySegmentationError, match="segment_3 in no memory"):
        validate_boundaries(
            [_boundary("segment_1", "segment_2"), _boundary("segment_4", "segment_5")],
            _index(),
        )


def test_memories_that_do_not_start_at_the_first_segment_are_refused() -> None:
    with pytest.raises(MemorySegmentationError, match="must start at segment_1"):
        validate_boundaries(
            [_boundary("segment_2", "segment_3"), _boundary("segment_4", "segment_5")],
            _index(),
        )


def test_memories_that_stop_before_the_last_segment_are_refused() -> None:
    with pytest.raises(MemorySegmentationError, match="must end at segment_5"):
        validate_boundaries(
            [_boundary("segment_1", "segment_2"), _boundary("segment_3", "segment_4")],
            _index(),
        )


def test_an_empty_division_is_refused() -> None:
    with pytest.raises(MemorySegmentationError, match="no memories"):
        validate_boundaries([], _index())


def test_a_memory_serializes_with_its_transcript_and_its_times_resolved() -> None:
    transcript = _transcript()
    client = _FakeClient([_boundary("segment_1", "segment_5", "The whole talk.")])

    payload = segment_transcript(transcript, client=client).to_payload()

    assert payload["model"] == "gpt-6.1-sol"
    assert payload["memory_count"] == 1
    assert payload["memories"][0] == {
        "index": 0,
        "start_segment_id": "segment_1",
        "end_segment_id": "segment_5",
        "start_seconds": 0.0,
        "end_seconds": 52.0,
        "transcript": " ".join(text for text, _, _ in TRANSCRIPT_LINES),
        "summary": "The whole talk.",
    }
