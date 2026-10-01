"""Tests for the main agent's two visual search tools, called directly with a real ConversationDeps.

The search services run for real against a `FakePool` answering their reads in order -- the
index state, the segments, the chapters, the count of unread keyframes, the keyframe texts, then
the frame scores or the keyframe-text scores. Only the query encoders are stood in for, so no
model loads. What these tests check is the tool's side: what it hands the service, the fields
the agent reads, which of them the citation check can collect, and the notes.
"""

import asyncio
import functools

import pytest

from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.services.visual_search import search_screen_text as search_screen_text_in_video
from backend.services.visual_search import search_visual_moments as search_moments_in_video
from backend.tests.fake_postgres import FakePool
from backend.video_agent.citations import spans_of
from backend.video_agent.prompt import VISUAL_PROCESSING_MESSAGE, VISUAL_UNAVAILABLE_MESSAGE
from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.search_screen_text import ScreenTextMoments, search_screen_text
from backend.video_agent.tools.search_screen_text import tool as screen_text_tool
from backend.video_agent.tools.search_visual_moments import PictureMatches, search_visual_moments
from backend.video_agent.tools.search_visual_moments import tool as moments_tool
from backend.video_agent.tools.visual_budget_spent import VisualBudgetSpent
from backend.video_agent.visual_budget import MAX_LOOKS, MAX_VISUAL_TOOL_CALLS

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

READY_STATE = [{"visual_status": "ready", "visual_error": None, "visual_index_version": CURRENT_VISUAL_INDEX_VERSION}]
NOT_READY_STATE = [{"visual_status": "indexing", "visual_error": None, "visual_index_version": None}]
OUTDATED_STATE = [{"visual_status": "ready", "visual_error": None, "visual_index_version": "clip@1fps"}]

SEGMENTS = [
    {"segment_id": "s0", "segment_index": 0, "start_seconds": 0.0, "end_seconds": 20.0, "boundary_kind": "video_start", "keyframe_times": [0.0]},
    {"segment_id": "s1", "segment_index": 1, "start_seconds": 20.0, "end_seconds": 40.0, "boundary_kind": "scene_change", "keyframe_times": [20.0]},
    {"segment_id": "s2", "segment_index": 2, "start_seconds": 40.0, "end_seconds": 60.0, "boundary_kind": "text_change", "keyframe_times": [40.0]},
]

CHAPTERS = [
    {"chapter_id": "c0", "chapter_index": 0, "title": "Opening", "summary": "", "start_seconds": 0.0, "end_seconds": 30.0},
    {"chapter_id": "c1", "chapter_index": 1, "title": "The diagram", "summary": "", "start_seconds": 30.0, "end_seconds": 60.0},
]


class FakeRunContext:
    """The single attribute the tools read off a RunContext."""

    def __init__(self, deps: ConversationDeps):
        self.deps = deps


def frame_scores(hits: dict[float, float]) -> list[dict]:
    """Frames two seconds apart over the minute, all near the background except the hits."""
    return [
        {"time_seconds": float(t), "similarity": hits.get(float(t), 0.05 + (t % 4) * 0.001)}
        for t in range(0, 60, 2)
    ]


def index_pool(*, texts: dict[float, str] | None = None, unread: int = 0, after: list[list[dict]] = ()) -> FakePool:
    """A ready index answered in the order both searches open it, then whatever `after` holds."""
    texts = texts or {}
    return FakePool(
        responses=[
            READY_STATE,
            SEGMENTS,
            CHAPTERS,
            [{"unread_count": unread}],
            [{"time_seconds": time, "ocr_text": text} for time, text in texts.items()],
            *after,
        ]
    )


def text_scores(texts: dict[float, str], scores: dict[float, float]) -> list[dict]:
    """The keyframe-text scores read for the meaning list, closest first."""
    return [
        {"time_seconds": time, "ocr_text": texts[time], "similarity": score}
        for time, score in sorted(scores.items(), key=lambda item: -item[1])
    ]


def _deps(pool: FakePool) -> ConversationDeps:
    return ConversationDeps(video_id=VIDEO_ID, current_time_seconds=130.0, pool=pool)


@pytest.fixture(autouse=True)
def fake_encoders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both searches with stand-in encoders, so SigLIP 2 and e5 never load."""
    monkeypatch.setattr(
        moments_tool,
        "search_moments_in_video",
        functools.partial(search_moments_in_video, image_query_encoder=lambda _: [1.0]),
    )
    monkeypatch.setattr(
        screen_text_tool,
        "search_screen_text_in_video",
        functools.partial(search_screen_text_in_video, on_screen_text_query_encoder=lambda _: [1.0]),
    )


def _search_picture(deps: ConversationDeps, query: str = "a diagram of servers") -> PictureMatches:
    return asyncio.run(search_visual_moments(FakeRunContext(deps), query))


def _search_screen(deps: ConversationDeps, query: str = "kafka partitions", words=None) -> ScreenTextMoments:
    return asyncio.run(search_screen_text(FakeRunContext(deps), query, words))


# --- search_visual_moments -----------------------------------------------------------------


def test_a_picture_hit_comes_back_as_a_frame_in_its_shot_and_is_not_citable() -> None:
    result = _search_picture(_deps(index_pool(after=[frame_scores({24.0: 0.4, 26.0: 0.42})])))

    [frame] = result.frames
    assert (frame.frame_seconds, frame.timestamp) == (26.0, "00:26")
    assert (frame.shot_start_seconds, frame.shot_end_seconds) == (20.0, 40.0)
    assert frame.chapter == "Opening"
    # How far a frame stood out ranks the frames; the agent is given the order, not the number.
    assert "score" not in frame.model_dump()
    assert frame.weak is False
    assert result.note is None
    # Resembling the query is not showing it: nothing here is a span the answer may cite.
    assert spans_of(result) == []


def test_when_nothing_stands_out_the_weak_frames_come_back_with_a_note_and_are_not_citable() -> None:
    flat = [{"time_seconds": float(t), "similarity": 0.05} for t in range(0, 60, 2)]

    result = _search_picture(_deps(index_pool(after=[flat])))

    assert [frame.frame_seconds for frame in result.frames] == [0.0, 20.0, 40.0]
    assert all(frame.weak for frame in result.frames)
    assert "Nothing stood out" in result.note and "weak" in result.note
    assert spans_of(result) == []


def test_a_video_with_no_frames_says_nothing_stood_out_and_there_was_nothing_to_show() -> None:
    result = _search_picture(_deps(index_pool(after=[[]])))

    assert result.frames == []
    assert "no frames to show instead" in result.note


@pytest.mark.parametrize(
    ("state", "expected", "message"),
    [
        (NOT_READY_STATE, "not ready (status: indexing)", VISUAL_PROCESSING_MESSAGE),
        (OUTDATED_STATE, "built with other models", VISUAL_UNAVAILABLE_MESSAGE),
    ],
)
@pytest.mark.parametrize("search", ["picture", "screen"])
def test_an_index_that_cannot_be_searched_tells_the_agent_what_to_say(search, state, expected, message) -> None:
    """The tools are offered only for a ready index, so this is an index that changed mid-turn."""
    deps = _deps(FakePool(responses=[state]))

    result = _search_picture(deps) if search == "picture" else _search_screen(deps, words=["kafka"])

    assert expected in result.note
    assert message in result.note
    assert spans_of(result) == []


@pytest.mark.parametrize("search", ["picture", "screen"])
def test_an_empty_query_searches_nothing(search) -> None:
    pool = index_pool()
    deps = _deps(pool)

    result = _search_picture(deps, "  ") if search == "picture" else _search_screen(deps, " \n")

    assert "query is empty" in result.note
    assert pool.recorded == []
    assert deps.visual_budget.tool_calls_used == 0


def test_a_picture_search_that_fails_is_reported_rather_than_failing_the_answer(monkeypatch, caplog) -> None:
    def broken_encoder(_query):
        raise RuntimeError("SigLIP did not load")

    monkeypatch.setattr(
        moments_tool,
        "search_moments_in_video",
        functools.partial(search_moments_in_video, image_query_encoder=broken_encoder),
    )

    result = _search_picture(_deps(index_pool()))

    assert result.frames == [] and "search failed" in result.note
    assert "picture search failed" in caplog.text


# --- search_screen_text --------------------------------------------------------------------


def test_screen_text_moments_come_back_citable_the_exact_words_first() -> None:
    texts = {20.0: "Kafka\nPartitions", 40.0: "How the brokers are laid out"}
    deps = _deps(index_pool(texts=texts, after=[text_scores(texts, {40.0: 0.9})]))

    result = _search_screen(deps, words=["kafka"])

    by_words, by_meaning = result.moments
    assert (by_words.start_seconds, by_words.end_seconds, by_words.timestamp) == (20.0, 40.0, "00:20-00:40")
    assert (by_words.found_by, by_words.matched_words) == (["text_characters"], ["kafka"])
    assert (by_words.on_screen_text, by_words.chapter, by_words.shot_boundary) == (
        "Kafka\nPartitions",
        "Opening",
        "scene_change",
    )
    assert (by_meaning.found_by, by_meaning.shot_boundary) == (["text_meaning"], "text_change")
    assert result.note is None
    # The text was read there: each moment is a span the answer may cite.
    assert spans_of(result) == [(20.0, 40.0), (40.0, 60.0)]


def test_with_no_words_the_screen_text_is_searched_by_meaning_only() -> None:
    texts = {20.0: "Kafka partitions"}
    deps = _deps(index_pool(texts=texts, after=[text_scores(texts, {20.0: 0.9})]))

    result = _search_screen(deps)

    [moment] = result.moments
    assert moment.found_by == ["text_meaning"] and moment.matched_words == []


def test_blank_words_are_dropped_and_words_past_five_left_out_with_a_note() -> None:
    texts = {40.0: "fff"}
    deps = _deps(index_pool(texts=texts, after=[text_scores(texts, {})]))

    result = _search_screen(deps, words=[" ", "a", "b", "\t", "c", "d", "e", "f"])

    assert result.moments == []
    assert "Only the first 5 words were looked for: a, b, c, d, e." in result.note
    assert "Nothing matched." in result.note


def test_only_blank_words_search_by_meaning_rather_than_failing() -> None:
    texts = {20.0: "Kafka partitions"}
    deps = _deps(index_pool(texts=texts, after=[text_scores(texts, {20.0: 0.9})]))

    result = _search_screen(deps, words=["", " \n "])

    assert [moment.found_by for moment in result.moments] == [["text_meaning"]]


def test_an_empty_screen_text_search_while_ocr_is_still_reading_says_the_text_may_be_there() -> None:
    result = _search_screen(_deps(index_pool(unread=12)), words=["kafka"])

    assert result.moments == []
    assert "Nothing matched." in result.note
    assert "OCR has not read the text of 12 keyframes yet" in result.note
    assert "does not mean it is not on screen" in result.note


def test_a_screen_text_search_that_fails_is_reported_rather_than_failing_the_answer(monkeypatch, caplog) -> None:
    def broken_encoder(_query):
        raise RuntimeError("e5 did not load")

    monkeypatch.setattr(
        screen_text_tool,
        "search_screen_text_in_video",
        functools.partial(search_screen_text_in_video, on_screen_text_query_encoder=broken_encoder),
    )

    result = _search_screen(_deps(index_pool(texts={20.0: "Kafka"})))

    assert result.moments == [] and "search failed" in result.note
    assert "on-screen text search failed" in caplog.text


# --- the visual budget -----------------------------------------------------------------------


@pytest.mark.parametrize("search", ["picture", "screen"])
def test_a_search_spends_one_visual_call_and_no_look_and_says_what_is_left(search) -> None:
    deps = _deps(index_pool(after=[frame_scores({26.0: 0.42})] if search == "picture" else []))

    result = _search_picture(deps) if search == "picture" else _search_screen(deps, words=["kafka"])

    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (1, 0)
    assert result.budget == f"{MAX_VISUAL_TOOL_CALLS - 1} visual tool calls and {MAX_LOOKS} looks left."


@pytest.mark.parametrize("search", ["picture", "screen"])
def test_after_six_visual_calls_a_search_does_no_work_and_says_the_budget_is_spent(search) -> None:
    pool = index_pool()
    deps = _deps(pool)
    for _ in range(MAX_VISUAL_TOOL_CALLS):
        deps.visual_budget.start_tool_call()

    result = _search_picture(deps) if search == "picture" else _search_screen(deps, words=["kafka"])

    assert isinstance(result, VisualBudgetSpent)
    assert pool.recorded == []
