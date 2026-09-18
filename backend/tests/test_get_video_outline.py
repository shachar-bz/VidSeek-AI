"""Tests for the conversation tool that reads the structure of the current video."""

import pytest
from pydantic_ai import RunContext

from backend.conversation_tools.deps import ConversationDeps
from backend.conversation_tools.get_video_outline import ChapterOutline, get_video_outline
from backend.core.errors import VideoNotFoundError
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
FIRST_CHAPTER_ID = "aaaaaaaa-1111-1111-1111-111111111111"
SECOND_CHAPTER_ID = "bbbbbbbb-2222-2222-2222-222222222222"
THIRD_CHAPTER_ID = "cccccccc-3333-3333-3333-333333333333"

# In the order the read returns them, which is the order they are watched in.
CHAPTER_ROWS = [
    {
        "chapter_id": FIRST_CHAPTER_ID,
        "chapter_index": 0,
        "title": "How the company started",
        "summary": "The founders describe leaving their jobs to build the first prototype.",
        "start_seconds": 0.0,
        "end_seconds": 310.0,
    },
    {
        "chapter_id": SECOND_CHAPTER_ID,
        "chapter_index": 1,
        "title": "Pricing strategy",
        "summary": "The speaker explains how pricing evolved after customer feedback.",
        "start_seconds": 310.0,
        "end_seconds": 375.0,
    },
    {
        "chapter_id": THIRD_CHAPTER_ID,
        "chapter_index": 2,
        "title": "What they would do differently",
        "summary": "A closing reflection on the hires and bets that did not pay off.",
        "start_seconds": 375.0,
        "end_seconds": 902.5,
    },
]

# What `select 1` answers with for a video that is recorded.
VIDEO_EXISTS_ROW = [{"?column?": 1}]


def _context(deps: ConversationDeps) -> RunContext[ConversationDeps]:
    """A RunContext carrying nothing but the deps.

    Built field by field rather than through the constructor, for the same reason
    `test_get_chapter_context` does: Pydantic AI has changed which of RunContext's other
    fields are required across versions, and a tool that only reads `ctx.deps` should not
    have a test that breaks when a field it never touches is added.
    """
    context = object.__new__(RunContext)
    object.__setattr__(context, "deps", deps)
    return context


def _read(responses: list[list[dict]]) -> tuple[object, FakePool]:
    """The outline, and the pool that answered the reads it took to build it."""
    pool = FakePool(responses=responses)
    deps = ConversationDeps(video_id=VIDEO_ID, pool=pool)
    return get_video_outline(_context(deps)), pool


def test_the_outline_is_read_for_the_video_the_conversation_is_about() -> None:
    """The tool takes no arguments at all. Which video it describes comes from the run's
    deps, so the agent cannot ask for the structure of a video it is not talking about.
    """
    _, pool = _read([CHAPTER_ROWS])

    assert pool.recorded[0].parameters == (VIDEO_ID,)


def test_the_chapters_come_back_in_the_order_they_are_watched_in() -> None:
    outline, _ = _read([CHAPTER_ROWS])

    assert [chapter.chapter_id for chapter in outline.chapters] == [
        FIRST_CHAPTER_ID,
        SECOND_CHAPTER_ID,
        THIRD_CHAPTER_ID,
    ]
    assert [chapter.chapter_index for chapter in outline.chapters] == [0, 1, 2]


def test_the_read_asks_the_database_for_that_order_rather_than_sorting_after() -> None:
    """Ordering in Python would be ordering whatever arrived, which for a capped or
    differently sorted read is not the same thing as the video's own order.
    """
    _, pool = _read([CHAPTER_ROWS])

    assert "order by chapter_index" in pool.statements[0]


def test_each_chapter_carries_its_title_summary_position_and_times() -> None:
    outline, _ = _read([CHAPTER_ROWS])
    chapter = outline.chapters[1]

    assert chapter.chapter_id == SECOND_CHAPTER_ID
    assert chapter.chapter_index == 1
    assert chapter.title == "Pricing strategy"
    assert chapter.summary == CHAPTER_ROWS[1]["summary"]
    assert (chapter.start_seconds, chapter.end_seconds) == (310.0, 375.0)


def test_a_chapter_is_given_without_any_of_its_contents() -> None:
    """The outline is for choosing where to look, not for reading. Its weight has to grow
    with the number of chapters rather than with the length of the video, which it only
    does while no memory or transcript text rides along.
    """
    assert set(ChapterOutline.model_fields) == {
        "chapter_id",
        "chapter_index",
        "title",
        "summary",
        "start_seconds",
        "end_seconds",
    }


def test_every_chapter_is_returned_rather_than_a_capped_page() -> None:
    many = [dict(CHAPTER_ROWS[0], chapter_index=index) for index in range(40)]

    outline, pool = _read([many])

    assert len(outline.chapters) == 40
    assert "limit" not in pool.statements[0].lower()


def test_a_video_that_has_not_been_divided_into_chapters_has_an_empty_outline() -> None:
    """A real video nothing has segmented yet. Empty is the truthful answer about its
    structure, not a failure to find it.
    """
    outline, _ = _read([[], VIDEO_EXISTS_ROW])

    assert outline.chapters == []


def test_a_video_id_that_describes_nothing_raises() -> None:
    pool = FakePool(responses=[[], []])
    deps = ConversationDeps(video_id=VIDEO_ID, pool=pool)

    with pytest.raises(VideoNotFoundError):
        get_video_outline(_context(deps))


def test_a_video_with_chapters_is_not_looked_up_a_second_time_to_prove_it_exists() -> None:
    """Chapters can only belong to a video that is there, so the existence check is worth a
    round trip in the one case that is ambiguous and nowhere else.
    """
    _, pool = _read([CHAPTER_ROWS])

    assert len(pool.recorded) == 1


def test_an_empty_outline_is_what_makes_the_video_worth_checking_for() -> None:
    _, pool = _read([[], VIDEO_EXISTS_ROW])

    assert len(pool.recorded) == 2
    assert "from public.videos" in pool.statements[1]
    assert pool.recorded[1].parameters == (VIDEO_ID,)


def test_the_existence_check_does_not_read_the_video_row() -> None:
    """`get_by_id` would answer the same question by fetching every column of a video the
    caller is about to throw away.
    """
    _, pool = _read([[], VIDEO_EXISTS_ROW])

    assert "select 1 from public.videos" in pool.statements[1]
    assert "select *" not in pool.statements[1]
