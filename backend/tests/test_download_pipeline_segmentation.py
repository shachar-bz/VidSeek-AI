"""Tests for the stage that turns a transcript into stored memories and chapters.

Both services this stage calls are model calls over a whole video, so both are stood in
for. What is under test is everything around them: which write happens first, how a memory
finds the id of the chapter it was grouped into, and what is kept when the grouping half
fails.
"""

from unittest.mock import patch

from backend.download_pipeline.result import CHAPTER_GROUPING_FAILED, SEGMENTATION_FAILED
from backend.download_pipeline.segmentation import segment_and_store
from backend.semantic_segmentation.chapters import VideoChapter, VideoChapters
from backend.semantic_segmentation.memories import VideoMemories, VideoMemory
from backend.services.transcripts import (
    NormalizedTranscript,
    TimingFidelity,
    TranscriptSegment,
)

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

SEGMENTATION_PATH = "backend.download_pipeline.segmentation.segment_transcript"
GROUPING_PATH = "backend.download_pipeline.segmentation.group_memories"
CHAPTERS_STORE_PATH = "backend.download_pipeline.segmentation.PostgresChapters"
MEMORIES_STORE_PATH = "backend.download_pipeline.segmentation.PostgresMemories"

TRANSCRIPT = NormalizedTranscript(
    source="captions",
    timing_fidelity=TimingFidelity.CAPTION,
    segments=[
        TranscriptSegment(index=index, start_seconds=index * 5.0, end_seconds=index * 5.0 + 5.0, text=f"line {index}")
        for index in range(4)
    ],
)


def _memory(index: int) -> VideoMemory:
    return VideoMemory(
        index=index,
        start_segment_id=f"S{index}",
        end_segment_id=f"S{index}",
        summary=f"summary {index}",
        segments=[TRANSCRIPT.segments[index]],
    )


MEMORIES = VideoMemories(
    source="captions", model="gpt-5.6-sol", memories=[_memory(index) for index in range(4)]
)

# Two chapters over four memories, so a wrong mapping shows up as a memory pointing at the
# chapter next door rather than at nothing.
CHAPTERS = VideoChapters(
    source="captions",
    model="gpt-5.6-sol",
    chapters=[
        VideoChapter(
            index=0,
            start_memory_id="M0",
            end_memory_id="M1",
            title="Opening",
            summary="The first half.",
            memories=MEMORIES.memories[:2],
        ),
        VideoChapter(
            index=1,
            start_memory_id="M2",
            end_memory_id="M3",
            title="Closing",
            summary="The second half.",
            memories=MEMORIES.memories[2:],
        ),
    ],
)


class _RecordingStore:
    """A store whose `replace` records what it was given and answers with `result`.

    `log` is shared between the two stores so a test can see which of them wrote first.
    """

    def __init__(self, name: str, result, log: list[str]):
        self.name = name
        self.result = result
        self.calls: list[tuple] = []
        self._log = log

    def __call__(self, pool=None):
        return self

    def replace(self, video_id, rows):
        self._log.append(self.name)
        self.calls.append((video_id, list(rows)))
        return self.result


def _run(*, memories=MEMORIES, chapters=CHAPTERS, chapter_ids=("chapter-0", "chapter-1")):
    """Run the stage with both model calls and both stores stood in for."""
    write_order: list[str] = []
    chapter_store = _RecordingStore("chapters", list(chapter_ids), write_order)
    memory_store = _RecordingStore(
        "memories",
        len(memories.memories) if isinstance(memories, VideoMemories) else 0,
        write_order,
    )
    segment = (
        patch(SEGMENTATION_PATH, side_effect=memories)
        if isinstance(memories, Exception)
        else patch(SEGMENTATION_PATH, return_value=memories)
    )
    group = (
        patch(GROUPING_PATH, side_effect=chapters)
        if isinstance(chapters, Exception)
        else patch(GROUPING_PATH, return_value=chapters)
    )
    with (
        segment,
        group,
        patch(CHAPTERS_STORE_PATH, chapter_store),
        patch(MEMORIES_STORE_PATH, memory_store),
    ):
        result = segment_and_store(VIDEO_ID, TRANSCRIPT)
    return result, chapter_store, memory_store, write_order


def test_a_video_is_divided_grouped_and_both_halves_stored() -> None:
    result, chapter_store, memory_store, write_order = _run()

    assert result.memory_count == 4
    assert result.chapter_count == 2
    assert result.problems == ()
    assert len(chapter_store.calls) == 1
    assert len(memory_store.calls) == 1


def test_every_memory_points_at_the_chapter_the_model_grouped_it_into() -> None:
    # The mapping is read off the grouping itself rather than recomputed from the time
    # ranges, so a memory can only land in the chapter that claimed it.
    _, _, memory_store, _ = _run()
    written = memory_store.calls[0][1]

    assert [row.chapter_id for row in written] == [
        "chapter-0",
        "chapter-0",
        "chapter-1",
        "chapter-1",
    ]


def test_a_chapter_is_written_before_the_memories_that_point_at_it() -> None:
    # A chapter's id is generated by the database, so there is no id for a memory to carry
    # until the chapter's own write has returned one.
    _, _, _, write_order = _run()

    assert write_order == ["chapters", "memories"]


def test_a_chapter_carries_the_model_that_grouped_it() -> None:
    _, chapter_store, _, _ = _run()

    assert {row.model for row in chapter_store.calls[0][1]} == {"gpt-5.6-sol"}


def test_a_transcript_that_could_not_be_divided_stores_nothing() -> None:
    result, chapter_store, memory_store, write_order = _run(memories=RuntimeError("the model refused"))

    assert result.problems == (SEGMENTATION_FAILED,)
    assert result.memory_count == 0
    assert chapter_store.calls == []
    assert memory_store.calls == []


def test_memories_survive_a_grouping_that_failed_and_are_stored_ungrouped() -> None:
    # `memories.chapter_id` is nullable precisely for this state, so a grouping the model
    # would not produce is no reason to throw away a division of the transcript that worked.
    result, chapter_store, memory_store, write_order = _run(chapters=RuntimeError("the model refused"))

    assert result.problems == (CHAPTER_GROUPING_FAILED,)
    assert result.memory_count == 4
    assert result.chapter_count == 0
    assert chapter_store.calls == []
    assert [row.chapter_id for row in memory_store.calls[0][1]] == [None] * 4
