"""Tests for the conversation tool that reads a memory together with its neighbours."""

import pytest
from pydantic_ai import ModelRetry, RunContext

from backend.conversation_tools.deps import ConversationDeps
from backend.conversation_tools.get_memory_context import MAX_CONTEXT_RANGE, get_memory_context
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
CHAPTER_ID = "66666666-7777-8888-9999-000000000000"
PRECEDING_CHAPTER_ID = "55555555-5555-5555-5555-555555555555"
FOLLOWING_CHAPTER_ID = "77777777-7777-7777-7777-777777777777"

TARGET_INDEX = 7
TARGET_ID = "aaaaaaaa-0007-0007-0007-000000000007"

CHAPTER_ROW = {
    "chapter_id": CHAPTER_ID,
    "chapter_index": 3,
    "title": "Word alignment",
    "summary": "How each word is timed against the audio.",
    "preceding_id": PRECEDING_CHAPTER_ID,
    "preceding_index": 2,
    "preceding_title": "Transcription",
    "preceding_summary": "Turning the audio into text.",
    "following_id": FOLLOWING_CHAPTER_ID,
    "following_index": 4,
    "following_title": "Caching the checkpoint",
    "following_summary": "Why the model downloads only once.",
}

FIRST_CHAPTER_ROW = {
    **CHAPTER_ROW,
    "chapter_index": 0,
    "preceding_id": None,
    "preceding_index": None,
    "preceding_title": None,
    "preceding_summary": None,
}


def _memory_row(memory_index: int, chapter_id: str | None = CHAPTER_ID) -> dict:
    """One `memories` row at a given position, with times that follow from that position."""
    return {
        "memory_id": TARGET_ID if memory_index == TARGET_INDEX else f"aaaaaaaa-{memory_index:04d}-0000-0000-000000000000",
        "video_id": VIDEO_ID,
        "chapter_id": chapter_id,
        "memory_index": memory_index,
        "text": f"what was said at position {memory_index}",
        "summary": f"Summary of position {memory_index}.",
        "start_seconds": float(memory_index * 30),
        "end_seconds": float(memory_index * 30 + 29),
    }


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


def _read(responses: list[list[dict]], **arguments) -> tuple:
    """Run the tool against reads answered in order: target, chapter, then window."""
    pool = FakePool(responses=responses)
    deps = ConversationDeps(video_id=VIDEO_ID, pool=pool)
    return get_memory_context(_context(deps), **arguments), pool


def _grouped(window_indices: list[int], chapter_row: dict = CHAPTER_ROW) -> list[list[dict]]:
    """The three reads for a grouped memory, given which positions its chapter can fill."""
    return [
        [_memory_row(TARGET_INDEX)],
        [chapter_row],
        [_memory_row(index) for index in window_indices],
    ]


def test_the_target_comes_back_with_the_memories_either_side_of_it() -> None:
    result, _ = _read(_grouped([6, 7, 8]), memory_id=TARGET_ID)

    assert result.target.memory_id == TARGET_ID
    assert [memory.text for memory in result.before] == ["what was said at position 6"]
    assert [memory.text for memory in result.after] == ["what was said at position 8"]


def test_the_target_is_not_repeated_among_its_own_context() -> None:
    """The window read covers the target as well, since it is one index range; the target
    belongs in `target` and nowhere else, or the model would count it twice.
    """
    result, _ = _read(_grouped([6, 7, 8]), memory_id=TARGET_ID)

    assert TARGET_ID not in [memory.memory_id for memory in result.before + result.after]


def test_context_is_one_memory_each_side_when_the_model_does_not_say() -> None:
    _, pool = _read(_grouped([6, 7, 8]), memory_id=TARGET_ID)

    assert pool.recorded[-1].parameters == (CHAPTER_ID, TARGET_INDEX - 1, TARGET_INDEX + 1)


def test_the_window_is_read_inside_the_targets_chapter_only() -> None:
    """The chapter filter is what "never cross a chapter boundary" comes down to: the next
    chapter's memories sit at adjacent indices and are excluded by chapter, not by range.
    """
    _, pool = _read(_grouped([6, 7, 8]), memory_id=TARGET_ID, context_range=2)

    assert pool.recorded[-1].parameters[0] == CHAPTER_ID


def test_memories_come_back_in_the_order_they_were_spoken() -> None:
    result, _ = _read(_grouped([4, 5, 6, 7, 8, 9, 10]), memory_id=TARGET_ID, context_range=3)

    spoken = result.before + [result.target] + result.after
    assert [memory.start_seconds for memory in spoken] == sorted(
        memory.start_seconds for memory in spoken
    )


def test_the_chapter_these_memories_belong_to_is_named() -> None:
    result, _ = _read(_grouped([6, 7, 8]), memory_id=TARGET_ID)

    assert result.chapter_id == CHAPTER_ID
    assert result.chapter_title == "Word alignment"
    assert result.chapter_summary == "How each word is timed against the audio."


def test_a_side_that_runs_out_of_chapter_names_the_chapter_beyond_it() -> None:
    result, _ = _read(_grouped([4, 5, 6, 7, 8, 9]), memory_id=TARGET_ID, context_range=3)

    assert result.after_boundary is not None
    assert result.after_boundary.reason == "chapter_end"
    assert result.after_boundary.chapter_id == FOLLOWING_CHAPTER_ID
    assert result.after_boundary.chapter_title == "Caching the checkpoint"
    assert result.after_boundary.chapter_summary == "Why the model downloads only once."


def test_a_boundary_on_one_side_does_not_shorten_the_other() -> None:
    """Three asked for, three available before and only two after: the short side stays
    short and the full side stays full, rather than the window shrinking to match.
    """
    result, _ = _read(_grouped([4, 5, 6, 7, 8, 9]), memory_id=TARGET_ID, context_range=3)

    assert len(result.before) == 3
    assert len(result.after) == 2
    assert result.before_boundary is None


def test_running_out_at_the_start_of_the_chapter_names_the_chapter_before_it() -> None:
    result, _ = _read(_grouped([6, 7, 8, 9, 10]), memory_id=TARGET_ID, context_range=3)

    assert result.before_boundary is not None
    assert result.before_boundary.reason == "chapter_start"
    assert result.before_boundary.chapter_id == PRECEDING_CHAPTER_ID


def test_the_first_chapter_of_a_video_has_no_chapter_before_it_to_point_at() -> None:
    """The boundary still fires -- context was cut short -- but there is nowhere further
    back to read, which is what the null chapter says.
    """
    result, _ = _read(
        _grouped([6, 7, 8], chapter_row=FIRST_CHAPTER_ROW), memory_id=TARGET_ID, context_range=3
    )

    assert result.before_boundary is not None
    assert result.before_boundary.reason == "chapter_start"
    assert result.before_boundary.chapter_id is None
    assert result.before_boundary.chapter_title is None


def test_a_range_the_chapter_fills_exactly_reports_no_boundary() -> None:
    """Nothing was withheld, so nothing is announced: a boundary means context was lost,
    not that the window happens to sit against the chapter's edge.
    """
    result, _ = _read(_grouped([5, 6, 7, 8, 9]), memory_id=TARGET_ID, context_range=2)

    assert result.before_boundary is None
    assert result.after_boundary is None


def test_a_memory_no_chapter_covers_yet_comes_back_alone_and_says_why() -> None:
    result, _ = _read([[_memory_row(TARGET_INDEX, chapter_id=None)]], memory_id=TARGET_ID)

    assert result.target.memory_id == TARGET_ID
    assert result.before == [] and result.after == []
    assert result.chapter_id is None
    assert result.before_boundary is not None
    assert result.before_boundary.reason == "memory_not_grouped"
    assert result.after_boundary is not None
    assert result.after_boundary.reason == "memory_not_grouped"


def test_a_memory_with_no_chapter_is_not_looked_up_in_one() -> None:
    """Nothing to look up: without a chapter there is no window to read and no neighbouring
    chapter to name, so the call is the one read that found the memory.
    """
    _, pool = _read([[_memory_row(TARGET_INDEX, chapter_id=None)]], memory_id=TARGET_ID)

    assert len(pool.statements) == 1


def test_a_range_beyond_what_one_call_returns_is_clamped_and_the_result_says_so() -> None:
    """Silently honouring a smaller range would leave the model unable to tell a clamped
    call from a chapter that really ended there.
    """
    result, pool = _read(_grouped([6, 7, 8]), memory_id=TARGET_ID, context_range=50)

    assert result.context_range_used == MAX_CONTEXT_RANGE
    assert pool.recorded[-1].parameters == (
        CHAPTER_ID,
        TARGET_INDEX - MAX_CONTEXT_RANGE,
        TARGET_INDEX + MAX_CONTEXT_RANGE,
    )


def test_no_context_is_a_legitimate_request_for_just_this_memory() -> None:
    result, _ = _read(_grouped([7]), memory_id=TARGET_ID, context_range=0)

    assert result.context_range_used == 0
    assert result.before == [] and result.after == []
    assert result.before_boundary is None and result.after_boundary is None


def test_a_negative_range_is_clamped_rather_than_failing_the_call() -> None:
    result, _ = _read(_grouped([7]), memory_id=TARGET_ID, context_range=-4)

    assert result.context_range_used == 0


def test_the_memory_is_looked_up_in_the_video_the_conversation_is_about() -> None:
    """The model supplies only the memory id. Which video it is read from comes from the
    run's deps, so an id belonging to another video finds nothing here.
    """
    _, pool = _read(_grouped([6, 7, 8]), memory_id=TARGET_ID)

    assert pool.recorded[0].parameters == (TARGET_ID, VIDEO_ID)


def test_an_id_no_memory_of_this_video_has_asks_the_model_to_try_again() -> None:
    with pytest.raises(ModelRetry):
        _read([[]], memory_id=TARGET_ID)


def test_an_id_that_is_not_an_id_at_all_is_refused_without_a_query() -> None:
    """A malformed id would make the `::uuid` cast raise a database error rather than a
    retry the model can act on, so it never reaches the database.
    """
    pool = FakePool(responses=[[]])
    deps = ConversationDeps(video_id=VIDEO_ID, pool=pool)

    with pytest.raises(ModelRetry):
        get_memory_context(_context(deps), memory_id="the third one")

    assert pool.statements == []
