"""Tests for the `chapters` table read as a chapter and the memories grouped into it."""

from backend.storage.postgres.chapters import PostgresChapters
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
CHAPTER_ID = "66666666-7777-8888-9999-000000000000"
MEMORY_ID_1 = "aaaaaaaa-1111-1111-1111-111111111111"
MEMORY_ID_2 = "bbbbbbbb-2222-2222-2222-222222222222"

CHAPTER_COLUMNS = {
    "chapter_id": CHAPTER_ID,
    "chapter_index": 2,
    "title": "Pricing strategy",
    "summary": "The speaker explains how pricing evolved after customer feedback.",
    "chapter_start_seconds": 310.0,
    "chapter_end_seconds": 375.0,
}

# The chapter's columns repeat on every joined row, which is what the single query buys.
JOINED_ROWS = [
    {
        **CHAPTER_COLUMNS,
        "memory_id": MEMORY_ID_1,
        "memory_summary": "The product originally cost $49 a month.",
        "memory_start_seconds": 310.0,
        "memory_end_seconds": 342.0,
    },
    {
        **CHAPTER_COLUMNS,
        "memory_id": MEMORY_ID_2,
        "memory_summary": "Early customers considered the price too high.",
        "memory_start_seconds": 342.0,
        "memory_end_seconds": 375.0,
    },
]

# What a left join answers with for a chapter whose memories were detached from it.
EMPTY_CHAPTER_ROWS = [
    {
        **CHAPTER_COLUMNS,
        "memory_id": None,
        "memory_summary": None,
        "memory_start_seconds": None,
        "memory_end_seconds": None,
    }
]


def _store(rows: list[dict]) -> tuple[PostgresChapters, FakePool]:
    pool = FakePool(rows=rows)
    return PostgresChapters(pool=pool), pool


def test_the_read_is_scoped_to_the_chapter_and_its_video() -> None:
    """A chapter belonging to another video must not resolve, so the video is part of the
    predicate rather than something the caller is trusted to have checked.
    """
    store, pool = _store(JOINED_ROWS)
    store.chapter_with_memories(VIDEO_ID, CHAPTER_ID)

    statement = pool.statements[0]
    assert "where c.id = %s::uuid and c.video_id = %s::uuid" in statement
    assert pool.recorded[0].parameters == (CHAPTER_ID, VIDEO_ID)


def test_the_chapter_and_its_memories_are_read_in_one_round_trip() -> None:
    store, pool = _store(JOINED_ROWS)
    store.chapter_with_memories(VIDEO_ID, CHAPTER_ID)

    assert len(pool.recorded) == 1
    assert "left join public.memories m on m.chapter_id = c.id" in pool.statements[0]


def test_memories_come_back_in_the_order_they_were_spoken() -> None:
    """Ordered on `memory_index` rather than `start_seconds`: the two agree because memories
    partition the transcript end to end, but only the index cannot tie.
    """
    store, pool = _store(JOINED_ROWS)
    chapter = store.chapter_with_memories(VIDEO_ID, CHAPTER_ID)

    assert "order by m.memory_index" in pool.statements[0]
    assert [memory.memory_id for memory in chapter.memories] == [MEMORY_ID_1, MEMORY_ID_2]


def test_the_chapter_carries_its_own_title_summary_position_and_times() -> None:
    store, _ = _store(JOINED_ROWS)
    chapter = store.chapter_with_memories(VIDEO_ID, CHAPTER_ID)

    assert chapter.chapter_id == CHAPTER_ID
    assert chapter.chapter_index == 2
    assert chapter.title == "Pricing strategy"
    assert chapter.summary == CHAPTER_COLUMNS["summary"]
    assert (chapter.start_seconds, chapter.end_seconds) == (310.0, 375.0)


def test_a_memory_carries_its_summary_and_timing_but_not_what_was_said() -> None:
    store, _ = _store(JOINED_ROWS)
    chapter = store.chapter_with_memories(VIDEO_ID, CHAPTER_ID)

    first = chapter.memories[0]
    assert first.memory_id == MEMORY_ID_1
    assert first.summary == "The product originally cost $49 a month."
    assert (first.start_seconds, first.end_seconds) == (310.0, 342.0)
    assert not hasattr(first, "text")


def test_every_memory_is_returned_rather_than_a_capped_page() -> None:
    store, pool = _store(JOINED_ROWS)
    chapter = store.chapter_with_memories(VIDEO_ID, CHAPTER_ID)

    assert len(chapter.memories) == len(JOINED_ROWS)
    assert "limit" not in pool.statements[0]


def test_a_chapter_with_no_memories_left_in_it_is_still_a_chapter() -> None:
    """`memories.chapter_id` is `on delete set null`, so a chapter can outlive its contents.
    The chapter genuinely exists, so it is answered with rather than reported missing.
    """
    store, _ = _store(EMPTY_CHAPTER_ROWS)
    chapter = store.chapter_with_memories(VIDEO_ID, CHAPTER_ID)

    assert chapter is not None
    assert chapter.title == "Pricing strategy"
    assert chapter.memories == []


def test_a_chapter_this_video_does_not_have_reads_as_none() -> None:
    store, _ = _store([])

    assert store.chapter_with_memories(VIDEO_ID, CHAPTER_ID) is None


# The second read: a chapter named, with the chapters either side of it. The chapter's own
# columns are unprefixed and each neighbour's are prefixed, which is what keeps three
# chapters' worth of the same four columns apart in one row.
NEIGHBOUR_ROW = {
    "chapter_id": CHAPTER_ID,
    "chapter_index": 2,
    "title": "Pricing strategy",
    "summary": CHAPTER_COLUMNS["summary"],
    "preceding_id": "55555555-5555-5555-5555-555555555555",
    "preceding_index": 1,
    "preceding_title": "Finding the first customers",
    "preceding_summary": "How the first ten customers were found.",
    "following_id": "77777777-7777-7777-7777-777777777777",
    "following_index": 3,
    "following_title": "Hiring the first engineer",
    "following_summary": "What the first engineering hire changed.",
}

# What the left joins answer with for the video's first chapter: itself, and no chapter
# one index below it.
FIRST_CHAPTER_NEIGHBOUR_ROW = {
    **NEIGHBOUR_ROW,
    "chapter_index": 0,
    "preceding_id": None,
    "preceding_index": None,
    "preceding_title": None,
    "preceding_summary": None,
}


def test_a_chapter_and_both_its_neighbours_come_back_from_one_read() -> None:
    """Three chapters in one row rather than three reads: a caller wants a neighbour exactly
    when it has run out of the chapter it was reading, so it needs all three at once.
    """
    store, pool = _store([NEIGHBOUR_ROW])
    found = store.with_neighbours(VIDEO_ID, CHAPTER_ID)

    assert found is not None
    assert found.chapter.title == "Pricing strategy"
    assert found.preceding is not None and found.preceding.chapter_index == 1
    assert found.following is not None and found.following.title == "Hiring the first engineer"
    assert len(pool.recorded) == 1


def test_neighbours_are_the_chapters_one_index_either_side_of_this_one() -> None:
    """0005_chapters.sql counts chapter_index from zero with no gaps, so adjacency is
    arithmetic on the index rather than a search through the video's times.
    """
    store, pool = _store([NEIGHBOUR_ROW])
    store.with_neighbours(VIDEO_ID, CHAPTER_ID)

    assert "preceding.chapter_index = chapter.chapter_index - 1" in pool.statements[0]
    assert "following.chapter_index = chapter.chapter_index + 1" in pool.statements[0]


def test_the_neighbour_read_is_scoped_to_the_chapter_and_its_video() -> None:
    store, pool = _store([NEIGHBOUR_ROW])
    store.with_neighbours(VIDEO_ID, CHAPTER_ID)

    assert "where chapter.id = %s::uuid and chapter.video_id = %s::uuid" in pool.statements[0]
    assert pool.recorded[0].parameters == (CHAPTER_ID, VIDEO_ID)


def test_naming_a_neighbour_does_not_read_its_memories() -> None:
    """A neighbour is offered as somewhere to read next, and reading it is the next call's
    job; naming three chapters should not cost three chapters' contents.
    """
    store, pool = _store([NEIGHBOUR_ROW])
    found = store.with_neighbours(VIDEO_ID, CHAPTER_ID)

    assert "public.memories" not in pool.statements[0]
    assert not hasattr(found.following, "memories")


def test_the_first_chapter_of_a_video_has_nothing_before_it() -> None:
    """The video's own edge, not a missing row: the left join is what lets the chapter still
    answer when there is no chapter one index below it.
    """
    store, _ = _store([FIRST_CHAPTER_NEIGHBOUR_ROW])
    found = store.with_neighbours(VIDEO_ID, CHAPTER_ID)

    assert found is not None
    assert found.preceding is None
    assert found.following is not None


def test_neighbours_of_a_chapter_this_video_does_not_have_read_as_none() -> None:
    store, _ = _store([])

    assert store.with_neighbours(VIDEO_ID, CHAPTER_ID) is None
