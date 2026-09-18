"""Tests for the conversation tool that reads one whole chapter of the current video."""

import pytest
from pydantic_ai import RunContext

from backend.conversation_tools.deps import ConversationDeps
from backend.conversation_tools.get_chapter_context import (
    ChapterContext,
    ChapterMemory,
    get_chapter_context,
)
from backend.core.errors import ChapterNotFoundError
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
CHAPTER_ID = "66666666-7777-8888-9999-000000000000"
OTHER_VIDEO_CHAPTER_ID = "99999999-9999-9999-9999-999999999999"
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

ROWS = [
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

EMPTY_CHAPTER_ROWS = [
    {
        **CHAPTER_COLUMNS,
        "memory_id": None,
        "memory_summary": None,
        "memory_start_seconds": None,
        "memory_end_seconds": None,
    }
]


def _context(deps: ConversationDeps) -> RunContext[ConversationDeps]:
    """A RunContext carrying nothing but the deps.

    Built field by field rather than through the constructor, for the same reason
    `test_memories_semantic_search` does: Pydantic AI has changed which of RunContext's
    other fields are required across versions, and a tool that only reads `ctx.deps` should
    not have a test that breaks when a field it never touches is added.
    """
    context = object.__new__(RunContext)
    object.__setattr__(context, "deps", deps)
    return context


def _read(chapter_id: str, rows: list[dict]) -> tuple[ChapterContext, FakePool]:
    pool = FakePool(rows=rows)
    deps = ConversationDeps(video_id=VIDEO_ID, pool=pool)
    return get_chapter_context(_context(deps), chapter_id), pool


def test_the_chapter_is_read_within_the_video_the_conversation_is_about() -> None:
    """The model supplies only a chapter id. Which video it is looked up in comes from the
    run's deps, so the agent cannot pull context out of a video it is not talking about.
    """
    _, pool = _read(CHAPTER_ID, ROWS)

    assert pool.recorded[0].parameters == (CHAPTER_ID, VIDEO_ID)


def test_the_chapter_answers_with_what_it_covers_and_when() -> None:
    chapter, _ = _read(CHAPTER_ID, ROWS)

    assert chapter.chapter_id == CHAPTER_ID
    assert chapter.chapter_index == 2
    assert chapter.title == "Pricing strategy"
    assert chapter.summary == CHAPTER_COLUMNS["summary"]
    assert (chapter.start_seconds, chapter.end_seconds) == (310.0, 375.0)


def test_every_memory_in_the_chapter_comes_back_earliest_first() -> None:
    chapter, _ = _read(CHAPTER_ID, ROWS)

    assert [memory.memory_id for memory in chapter.memories] == [MEMORY_ID_1, MEMORY_ID_2]
    assert [memory.start_seconds for memory in chapter.memories] == [310.0, 342.0]


def test_a_memory_is_given_as_a_summary_and_a_timespan_only() -> None:
    """What was actually said is `memories_semantic_search`'s job. A chapter is read for its
    shape, and carrying every memory's speech would make the longest chapters the dearest.
    """
    chapter, _ = _read(CHAPTER_ID, ROWS)

    assert chapter.memories[0].summary == "The product originally cost $49 a month."
    assert (chapter.memories[0].start_seconds, chapter.memories[0].end_seconds) == (310.0, 342.0)
    assert set(ChapterMemory.model_fields) == {
        "memory_id",
        "summary",
        "start_seconds",
        "end_seconds",
    }


def test_a_chapter_with_nothing_in_it_is_returned_rather_than_reported_missing() -> None:
    chapter, _ = _read(CHAPTER_ID, EMPTY_CHAPTER_ROWS)

    assert chapter.title == "Pricing strategy"
    assert chapter.memories == []


def test_a_chapter_this_video_does_not_have_raises() -> None:
    """Covers both an id that exists nowhere and one belonging to another video: the read is
    scoped to the video, so the two reach the tool as the same empty result.
    """
    pool = FakePool(rows=[])
    deps = ConversationDeps(video_id=VIDEO_ID, pool=pool)

    with pytest.raises(ChapterNotFoundError):
        get_chapter_context(_context(deps), OTHER_VIDEO_CHAPTER_ID)
