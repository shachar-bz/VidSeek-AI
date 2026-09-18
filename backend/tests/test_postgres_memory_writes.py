"""Tests for writing a video's memories to the `memories` table.

The reads of the same table are covered by `test_postgres_memories.py`; these cover the
writer the memory-segmentation stage needed.
"""

from dataclasses import replace

from backend.storage.postgres import NewMemory, PostgresMemories
from backend.storage.postgres.memories import TABLE_NAME
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
CHAPTER_ID = "99999999-8888-7777-6666-555555555555"

MEMORIES = [
    NewMemory(
        memory_index=0,
        text="Hello and welcome.",
        summary="The speaker introduces the talk.",
        start_seconds=0.0,
        end_seconds=12.5,
        chapter_id=CHAPTER_ID,
        model="gpt-5.6-sol",
    ),
    NewMemory(
        memory_index=1,
        text="Today we are covering three things.",
        summary="The speaker lays out the agenda.",
        start_seconds=12.5,
        end_seconds=30.0,
        chapter_id=CHAPTER_ID,
        model="gpt-5.6-sol",
    ),
]


def _memories() -> tuple[PostgresMemories, FakePool]:
    pool = FakePool(rows=[])
    return PostgresMemories(pool=pool), pool


def test_memories_are_written_as_one_statement_per_batch_not_per_memory() -> None:
    memories, pool = _memories()
    written = memories.replace(VIDEO_ID, MEMORIES)

    assert written == len(MEMORIES)
    assert pool.recorded[0].many is True
    assert len(pool.recorded[0].parameters) == len(MEMORIES)


def test_a_memory_carries_its_chapter_and_the_times_the_transcript_measured() -> None:
    memories, pool = _memories()
    memories.replace(VIDEO_ID, MEMORIES)

    assert pool.recorded[0].parameters[0] == (
        VIDEO_ID,
        CHAPTER_ID,
        0,
        "Hello and welcome.",
        "The speaker introduces the talk.",
        0.0,
        12.5,
        "gpt-5.6-sol",
    )


def test_a_memory_that_has_not_been_grouped_is_written_without_a_chapter() -> None:
    # The state every memory is in between segmentation and grouping, and the state they
    # are all left in when grouping fails.
    memories, pool = _memories()
    memories.replace(VIDEO_ID, [replace(MEMORIES[0], chapter_id=None)])

    assert pool.recorded[0].parameters[0][1] is None


def test_a_position_that_already_exists_is_overwritten_rather_than_duplicated() -> None:
    # Overwriting in place keeps a memory's id stable, which is what stops a re-run from
    # orphaning the vectors in `memory_embeddings` that point at it.
    memories, pool = _memories()
    memories.replace(VIDEO_ID, MEMORIES)

    assert "on conflict (video_id, memory_index) do update set" in pool.statements[0]


def test_a_resegmentation_into_fewer_memories_leaves_no_tail_behind() -> None:
    memories, pool = _memories()
    memories.replace(VIDEO_ID, MEMORIES[:1])

    assert f"delete from public.{TABLE_NAME}" in pool.statements[-1]
    assert pool.recorded[-1].parameters == (VIDEO_ID, 1)


def test_a_video_with_no_memories_deletes_what_was_there_without_writing_anything() -> None:
    memories, pool = _memories()

    assert memories.replace(VIDEO_ID, []) == 0
    assert len(pool.recorded) == 1
    assert pool.recorded[0].parameters == (VIDEO_ID, 0)


def test_writing_and_trimming_are_one_transaction() -> None:
    memories, pool = _memories()
    memories.replace(VIDEO_ID, MEMORIES)

    assert pool.transactions == 1
