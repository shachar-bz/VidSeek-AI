"""Tests for the `memories` table read as moments in place, rather than as embedding input."""

from backend.storage.postgres.memories import PostgresMemories
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
OTHER_VIDEO_ID = "99999999-9999-9999-9999-999999999999"
CHAPTER_ID = "66666666-7777-8888-9999-000000000000"
MEMORY_ID = "aaaaaaaa-1111-1111-1111-111111111111"

ROW = {
    "memory_id": MEMORY_ID,
    "video_id": VIDEO_ID,
    "chapter_id": CHAPTER_ID,
    "memory_index": 7,
    "text": "the aligner needs the audio at sixteen kilohertz, mono",
    "summary": "States the aligner's audio format.",
    "start_seconds": 90.0,
    "end_seconds": 104.5,
}

UNGROUPED_ROW = {**ROW, "chapter_id": None, "memory_index": 0}


def _store(rows: list[dict] | None = None) -> tuple[PostgresMemories, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresMemories(pool=pool), pool


def test_a_memory_is_read_with_its_index_text_summary_and_times() -> None:
    store, _ = _store([ROW])
    memory = store.get(VIDEO_ID, MEMORY_ID)

    assert memory is not None
    assert memory.memory_id == MEMORY_ID
    assert memory.chapter_id == CHAPTER_ID
    assert memory.memory_index == 7
    assert memory.text == ROW["text"]
    assert memory.summary == ROW["summary"]
    assert (memory.start_seconds, memory.end_seconds) == (90.0, 104.5)


def test_a_memory_is_looked_up_by_video_as_well_as_by_id() -> None:
    """A memory id alone is enough to find the row, so filtering on the video is what stops
    an id from another video answering with that video's transcript.
    """
    store, pool = _store([ROW])
    store.get(VIDEO_ID, MEMORY_ID)

    assert "where id = %s::uuid and video_id = %s::uuid" in pool.statements[0]
    assert pool.recorded[0].parameters == (MEMORY_ID, VIDEO_ID)


def test_a_memory_the_video_does_not_have_reads_as_nothing() -> None:
    store, _ = _store([])

    assert store.get(OTHER_VIDEO_ID, MEMORY_ID) is None


def test_an_ungrouped_memory_reads_back_with_no_chapter() -> None:
    store, _ = _store([UNGROUPED_ROW])
    memory = store.get(VIDEO_ID, MEMORY_ID)

    assert memory is not None
    assert memory.chapter_id is None


def test_a_window_is_bounded_by_the_chapter_and_the_index_range() -> None:
    """Both halves of "never cross a chapter boundary" are in the query: the chapter filter
    is what a memory of the next chapter fails, and the range is what the caller asked for.
    """
    store, pool = _store([ROW])
    store.chapter_window(CHAPTER_ID, 6, 8)

    assert "where chapter_id = %s::uuid and memory_index between %s and %s" in pool.statements[0]
    assert pool.recorded[0].parameters == (CHAPTER_ID, 6, 8)


def test_a_window_is_ordered_by_position_in_the_video() -> None:
    store, pool = _store([ROW])
    store.chapter_window(CHAPTER_ID, 6, 8)

    assert "order by memory_index" in pool.statements[0]


def test_a_window_the_chapter_cannot_fill_returns_what_it_has() -> None:
    """A range running past the chapter's edge is not an error; the shorter list is how the
    caller learns where the chapter ended.
    """
    store, _ = _store([ROW])

    assert len(store.chapter_window(CHAPTER_ID, 0, 100)) == 1
