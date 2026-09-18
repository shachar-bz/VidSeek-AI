"""Tests for writing a video's chapters to the `chapters` table.

The reads of the same table are covered by `test_postgres_chapters.py`. These are kept
apart because the writer is what the chapter-grouping stage needed and the reads are what
the video agent needs, and the two answer to different callers.
"""

from backend.storage.postgres import NewChapter, PostgresChapters
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

CHAPTERS = [
    NewChapter(
        chapter_index=0,
        title="Setting up",
        summary="What the talk is about.",
        start_seconds=0.0,
        end_seconds=61.5,
        model="gpt-5.6-sol",
    ),
    NewChapter(
        chapter_index=1,
        title="The argument",
        summary="Why the approach works.",
        start_seconds=61.5,
        end_seconds=180.0,
        model="gpt-5.6-sol",
    ),
]


def _chapters(written_ids: list[str] | None = None) -> tuple[PostgresChapters, FakePool]:
    """A store whose writes answer with `written_ids`, one generated id per chapter."""
    ids = written_ids if written_ids is not None else ["chapter-0", "chapter-1"]
    pool = FakePool(responses=[[{"id": value}] for value in ids])
    return PostgresChapters(pool=pool), pool


def test_each_chapter_comes_back_with_the_id_the_database_generated_for_it() -> None:
    # The ids are the whole reason this write reads anything back: a memory points at the
    # chapter it was grouped into, and nothing knows that id until the chapter is written.
    chapters, _ = _chapters(["first", "second"])

    assert chapters.replace(VIDEO_ID, CHAPTERS) == ["first", "second"]


def test_the_ids_come_back_in_chapter_order_however_the_chapters_arrived() -> None:
    # A caller matches the id at position n to the chapter it handed over at n, so the two
    # sequences have to be in the same order whatever order the caller built its list in.
    chapters, pool = _chapters(["first", "second"])
    chapters.replace(VIDEO_ID, list(reversed(CHAPTERS)))

    written_indexes = [item.parameters[1] for item in pool.recorded[:2]]
    assert written_indexes == [0, 1]


def test_a_chapter_carries_the_times_its_memories_measured() -> None:
    chapters, pool = _chapters()
    chapters.replace(VIDEO_ID, CHAPTERS)

    assert pool.recorded[0].parameters == (
        VIDEO_ID,
        0,
        "Setting up",
        "What the talk is about.",
        0.0,
        61.5,
        "gpt-5.6-sol",
    )


def test_a_position_that_already_exists_is_overwritten_rather_than_duplicated() -> None:
    # The upsert is what lets a re-grouping replace a video's chapters in place instead of
    # leaving the old ones interleaved with the new.
    chapters, pool = _chapters()
    chapters.replace(VIDEO_ID, CHAPTERS)

    assert "on conflict (video_id, chapter_index) do update set" in pool.statements[0]


def test_a_regrouping_into_fewer_chapters_leaves_no_tail_behind() -> None:
    chapters, pool = _chapters(["only"])
    chapters.replace(VIDEO_ID, CHAPTERS[:1])

    assert "chapter_index >= %s" in pool.statements[-1]
    assert pool.recorded[-1].parameters == (VIDEO_ID, 1)


def test_a_video_with_no_chapters_deletes_what_was_there_without_writing_anything() -> None:
    chapters, pool = _chapters([])

    assert chapters.replace(VIDEO_ID, []) == []
    assert len(pool.recorded) == 1
    assert pool.recorded[0].parameters == (VIDEO_ID, 0)


def test_writing_and_trimming_are_one_transaction() -> None:
    # A video left briefly with no chapters at all is a state nothing downstream should be
    # able to observe, so the replacement lands as a unit or not at all.
    chapters, pool = _chapters()
    chapters.replace(VIDEO_ID, CHAPTERS)

    assert pool.transactions == 1
