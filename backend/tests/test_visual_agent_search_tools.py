"""Tests for the visual sub-agent's two search tools, called directly with a real VisualDeps.

The search services run for real against a `FakePool` answering their reads in order -- the
index state, the segments, the chapters, the count of unread keyframes, the keyframe texts, the
frame scores. Only the query encoder is stood in for, so no model loads. What these tests check
is the tool's side: the words it hands the service, the budget it spends, the spans it records
for the findings check, and what it tells the agent when the index cannot be searched.
"""

import asyncio
import functools

import pytest

from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.services.visual_search import search_visual_moments as search_moments_in_video
from backend.tests.fake_postgres import FakePool
from backend.visual_agent.budget import MAX_TOOL_CALLS
from backend.visual_agent.tools.budget_spent import BudgetSpent
from backend.visual_agent.tools.deps import VisualDeps
from backend.visual_agent.tools.search_visual_moments import search_visual_moments
from backend.visual_agent.tools.search_visual_moments import tool as moments_tool
from backend.visual_agent.tools.search_visual_text import search_visual_text
from backend.visual_agent.tools.searched_moments import SearchedMoments

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

READY_STATE = [{"visual_status": "ready", "visual_error": None, "visual_index_version": CURRENT_VISUAL_INDEX_VERSION}]

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

    def __init__(self, deps: VisualDeps):
        self.deps = deps


def frame_scores(hits: dict[float, float]) -> list[dict]:
    """Frames two seconds apart over the minute, all near the background except the hits."""
    return [
        {"time_seconds": float(t), "similarity": hits.get(float(t), 0.05 + (t % 4) * 0.001)}
        for t in range(0, 60, 2)
    ]


def index_pool(*, texts: dict[float, str] | None = None, unread: int = 0, after: list[list[dict]] = ()) -> FakePool:
    """A ready index answered in the order both searches read it, then whatever `after` holds."""
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


def _deps(pool: FakePool, current_time_seconds: float | None = 130.0) -> VisualDeps:
    return VisualDeps(video_id=VIDEO_ID, current_time_seconds=current_time_seconds, pool=pool)


@pytest.fixture(autouse=True)
def fake_encoders(monkeypatch: pytest.MonkeyPatch) -> None:
    """The moment search with a stand-in encoder, so SigLIP 2 never loads."""
    monkeypatch.setattr(
        moments_tool,
        "search_moments_in_video",
        functools.partial(search_moments_in_video, image_query_encoder=lambda _: [1.0]),
    )


def _search_moments(deps: VisualDeps, query: str = "the architecture diagram"):
    return asyncio.run(search_visual_moments(FakeRunContext(deps), query))


def _search_text(deps: VisualDeps, words: list[str]):
    return asyncio.run(search_visual_text(FakeRunContext(deps), words))


# --- search_visual_moments -----------------------------------------------------------------


def test_a_picture_match_comes_back_placed_but_needs_a_look_before_it_is_citable() -> None:
    deps = _deps(index_pool(after=[frame_scores({24.0: 0.4, 26.0: 0.42})]))

    result = _search_moments(deps)

    assert isinstance(result, SearchedMoments)
    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds, moment.timestamps) == (24.0, 26.0, "00:24-00:26")
    assert (moment.chapter, moment.segment_index, moment.segment_boundary) == ("Opening", 1, "scene_change")
    assert moment.found_by == ["image"]
    assert moment.peak_z_score is not None and moment.peak_z_score > 1.5
    assert moment.needs_look is True
    assert result.note is None
    # Resembling the query is not showing it: nothing is citable until a look.
    assert deps.spans == []
    assert deps.budget.tool_calls_used == 1
    assert f"{MAX_TOOL_CALLS - 1} tool calls" in result.budget


def test_an_empty_query_searches_nothing_and_spends_nothing() -> None:
    deps = _deps(index_pool())

    result = _search_moments(deps, query="   ")

    assert "query is empty" in result.note
    assert deps.budget.tool_calls_used == 0


def test_nothing_matching_says_so() -> None:
    deps = _deps(index_pool(after=[[{"time_seconds": float(t), "similarity": 0.05} for t in range(0, 60, 2)]]))

    result = _search_moments(deps)

    assert result.moments == [] and result.note == "Nothing matched."
    assert deps.spans == []


@pytest.mark.parametrize("search", ["moments", "text"])
def test_an_index_not_ready_sends_the_agent_to_the_current_moment(search: str) -> None:
    pool = FakePool(responses=[[{"visual_status": "indexing", "visual_error": None, "visual_index_version": None}]])
    deps = _deps(pool)

    result = _search_moments(deps) if search == "moments" else _search_text(deps, ["kafka"])

    assert result.moments == []
    assert "not ready (status: indexing)" in result.note
    assert "02:10 (130.0 s)" in result.note and "view_sequence" in result.note
    assert deps.spans == []
    assert deps.budget.tool_calls_used == 1


def test_an_outdated_index_is_not_searched_and_with_no_position_the_agent_is_told_where_else_to_look() -> None:
    pool = FakePool(responses=[[{"visual_status": "ready", "visual_error": None, "visual_index_version": "clip@1fps"}]])

    result = _search_moments(_deps(pool, current_time_seconds=None))

    assert result.moments == []
    assert "built with other models" in result.note
    assert "frames the question points to" in result.note


def test_a_search_that_fails_is_reported_rather_than_failing_the_investigation(monkeypatch, caplog) -> None:
    def broken_encoder(_query):
        raise RuntimeError("SigLIP did not load")

    monkeypatch.setattr(
        moments_tool,
        "search_moments_in_video",
        functools.partial(search_moments_in_video, image_query_encoder=broken_encoder),
    )
    deps = _deps(index_pool())

    result = _search_moments(deps)

    assert result.moments == [] and "search failed" in result.note
    assert deps.budget.tool_calls_used == 1
    assert "visual moment search failed" in caplog.text


def test_after_six_calls_the_search_does_no_work() -> None:
    pool = index_pool()
    deps = _deps(pool)
    deps.budget.tool_calls_used = MAX_TOOL_CALLS

    assert isinstance(_search_moments(deps), BudgetSpent)
    assert pool.recorded == []


# --- search_visual_text --------------------------------------------------------------------


def test_the_words_found_come_back_with_their_moment_and_become_citable() -> None:
    deps = _deps(index_pool(texts={20.0: "Kafka\nPartitions", 40.0: "Consumer groups"}))

    result = _search_text(deps, ["kafka", "partitions"])

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (20.0, 40.0)
    assert moment.found_by == ["text_characters"]
    assert moment.matched_words == ["kafka", "partitions"]
    assert moment.needs_look is False
    assert moment.on_screen_text == "Kafka\nPartitions"
    assert (moment.chapter, moment.peak_z_score) == ("Opening", None)
    assert deps.spans == [(20.0, 40.0)]
    assert deps.budget.tool_calls_used == 1


def test_blank_words_are_dropped_and_words_past_five_left_out_with_a_note() -> None:
    deps = _deps(index_pool(texts={40.0: "fff"}))

    result = _search_text(deps, [" ", "a", "b", "\t", "c", "d", "e", "f"])

    assert result.moments == []
    assert "Only the first 5 words were looked for: a, b, c, d, e." in result.note
    assert "Nothing matched." in result.note


def test_no_words_searches_nothing_and_spends_nothing() -> None:
    pool = index_pool()
    deps = _deps(pool)

    result = _search_text(deps, ["", " \n "])

    assert "no words were given" in result.note
    assert deps.budget.tool_calls_used == 0
    assert pool.recorded == []


def test_an_empty_text_search_while_ocr_is_still_reading_says_it_may_have_missed_text() -> None:
    result = _search_text(_deps(index_pool(unread=12)), ["kafka"])

    assert result.moments == []
    assert "Nothing matched." in result.note
    assert "OCR has not read the text of 12 keyframes yet" in result.note


def test_the_two_searches_share_the_budget_with_the_other_tools() -> None:
    deps = _deps(FakePool())

    for _ in range(MAX_TOOL_CALLS // 2):
        _search_moments(deps)
        _search_text(deps, ["kafka"])

    assert deps.budget.tool_calls_used == MAX_TOOL_CALLS
    assert isinstance(_search_text(deps, ["kafka"]), BudgetSpent)
