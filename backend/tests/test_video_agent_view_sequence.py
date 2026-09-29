"""Tests for the video agent's view_sequence tool, and the scenes and prompt it relies on.

The tool is called directly with a real ConversationDeps. The index state, segments and chapters
come from a `FakePool` answering reads in order -- the state, the segments, the chapters of the
video map, then the chapter outline `chapter_at` reads. The frame source hands back small real
JPEGs, so the grid is really built; the image analyzer is a stand-in that records what it was
sent. What the answer may cite is read the way the runner reads it: `spans_of` on the result.
"""

import asyncio
import io

import pytest
from PIL import Image

from backend.services.video_frames import JPEG, FrameExtractionError
from backend.services.video_frames.grid import CELL_LONG_SIDE
from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.services.visual_search import VideoVisualMap
from backend.storage.postgres import StoredVisualSegment
from backend.tests.fake_postgres import FakePool
from backend.tests.fake_visual_looks import FakeFrameSource, FakeImageAnalyzer, FakeRunContext, look_deps
from backend.video_agent.citations import spans_of
from backend.video_agent.image_analysis import SequenceCell, sequence_prompt
from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.view_sequence import (
    MAX_FRAME_COUNT,
    MIN_FRAME_COUNT,
    ViewedSequence,
    view_sequence,
)
from backend.video_agent.tools.visual_budget_spent import VisualBudgetSpent
from backend.video_agent.visual_budget import MAX_LOOKS, MAX_VISUAL_TOOL_CALLS

READY_STATE = [{"visual_status": "ready", "visual_error": None, "visual_index_version": CURRENT_VISUAL_INDEX_VERSION}]
INDEXING_STATE = [{"visual_status": "indexing", "visual_error": None, "visual_index_version": None}]

# Two scenes: 0-20 s, then a cut, then 20-60 s, which a slide change at 40 s does not split.
SEGMENTS = [
    {"segment_id": "s0", "segment_index": 0, "start_seconds": 0.0, "end_seconds": 20.0, "boundary_kind": "video_start", "keyframe_times": [0.0]},
    {"segment_id": "s1", "segment_index": 1, "start_seconds": 20.0, "end_seconds": 40.0, "boundary_kind": "scene_change", "keyframe_times": [20.0]},
    {"segment_id": "s2", "segment_index": 2, "start_seconds": 40.0, "end_seconds": 60.0, "boundary_kind": "text_change", "keyframe_times": [40.0]},
]

CHAPTERS = [
    {"chapter_id": "c0", "chapter_index": 0, "title": "Opening", "summary": "", "start_seconds": 0.0, "end_seconds": 30.0},
    {"chapter_id": "c1", "chapter_index": 1, "title": "The kitchen", "summary": "", "start_seconds": 30.0, "end_seconds": 60.0},
]


def ready_pool() -> FakePool:
    return FakePool(responses=[READY_STATE, SEGMENTS, CHAPTERS, CHAPTERS])


def not_ready_pool() -> FakePool:
    return FakePool(responses=[INDEXING_STATE, CHAPTERS])


def _deps(
    pool: FakePool | None = None,
    *,
    frame_source: FakeFrameSource | None = None,
    analyzer: FakeImageAnalyzer | None = None,
) -> ConversationDeps:
    return look_deps(pool or ready_pool(), frame_source=frame_source, analyzer=analyzer)


def _view(deps: ConversationDeps, start: float, question: str = "Does he pick up the cup?", **options):
    return asyncio.run(view_sequence(FakeRunContext(deps), start, question, **options))


# --- one scene ------------------------------------------------------------------------------


def test_a_window_inside_one_scene_is_one_grid_costing_one_call_and_one_look() -> None:
    source, analyzer = FakeFrameSource(), FakeImageAnalyzer()
    deps = _deps(frame_source=source, analyzer=analyzer)

    result = _view(deps, 22.0, end_seconds=32.0)

    assert isinstance(result, ViewedSequence)
    assert [(f.time_seconds, f.timestamp, f.scene, f.chapter, f.observation) for f in result.frames] == [
        (22.0, "00:22", 1, "Opening", "Cell 1"),
        (24.0, "00:24", 1, "Opening", "Cell 2"),
        (26.0, "00:26", 1, "Opening", "Cell 3"),
        (28.0, "00:28", 1, "Opening", "Cell 4"),
        (30.0, "00:30", 1, "The kitchen", "Cell 5"),
        (32.0, "00:32", 1, "The kitchen", "Cell 6"),
    ]
    assert (result.first_frame_seconds, result.last_frame_seconds) == (22.0, 32.0)
    # A slide change at 40 s is not a cut: the scene runs on to 60 s.
    assert [
        (s.scene, s.start_seconds, s.end_seconds, s.frames, s.scene_start_seconds, s.scene_end_seconds)
        for s in result.scenes
    ] == [(1, 22.0, 32.0, "00:22-00:32", 20.0, 60.0)]
    assert result.answer == "He picks up the cup."
    assert result.note is None
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (1, 1)
    assert result.budget == f"{MAX_VISUAL_TOOL_CALLS - 1} visual tool calls and {MAX_LOOKS - 1} looks left."
    # Frames are extracted at the grid's cell size, and the image model gets one JPEG grid.
    assert source.calls[0]["long_side"] == CELL_LONG_SIDE
    [(question, grid, cells)] = analyzer.sequence_calls
    assert question == "Does he pick up the cup?"
    assert Image.open(io.BytesIO(grid)).format == "JPEG"
    assert [cell.scene for cell in cells] == [1] * 6


def test_only_the_frames_looked_at_are_citable_never_the_whole_scene() -> None:
    result = _view(_deps(), 22.0, end_seconds=32.0)

    assert spans_of(result) == [(22.0, 32.0)]


def test_with_no_end_the_window_runs_to_the_end_of_the_start_s_shot() -> None:
    source = FakeFrameSource()

    result = _view(_deps(frame_source=source), 22.0, frame_count=3)

    assert source.calls[0]["times"] == [22.0, 30.75, 39.5]
    assert "to the end of its shot, 00:39" in result.note


def test_with_no_end_and_its_shot_about_to_end_the_window_runs_the_fixed_stretch() -> None:
    source = FakeFrameSource()

    result = _view(_deps(frame_source=source), 39.0, frame_count=3)

    assert source.calls[0]["times"] == [39.0, 44.0, 49.0]
    assert "shot ends too soon after the start, so the window runs 10 s, to 00:49" in result.note


def test_a_window_of_one_instant_is_widened_either_side() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, 26.0, end_seconds=26.0, frame_count=3)

    assert source.calls[0]["times"] == [24.0, 26.0, 28.0]
    assert "widened to 00:24-00:28" in result.note
    assert deps.visual_budget.tool_calls_used == 1


def test_each_frame_carries_its_number_in_the_grid() -> None:
    result = _view(_deps(), 22.0, end_seconds=26.0, frame_count=3)

    assert [(frame.frame, frame.observation) for frame in result.frames] == [
        (1, "Cell 1"),
        (2, "Cell 2"),
        (3, "Cell 3"),
    ]


# --- scene cuts -----------------------------------------------------------------------------


def test_a_window_across_a_cut_is_not_cut_but_says_which_frames_come_from_which_scene() -> None:
    analyzer = FakeImageAnalyzer()
    deps = _deps(analyzer=analyzer)

    result = _view(deps, 10.0, end_seconds=30.0, frame_count=5)

    assert [(f.time_seconds, f.scene) for f in result.frames] == [(10.0, 1), (15.0, 1), (20.0, 2), (25.0, 2), (30.0, 2)]
    assert [
        (s.scene, s.start_seconds, s.end_seconds, s.frames, s.scene_start_seconds, s.scene_end_seconds)
        for s in result.scenes
    ] == [
        (1, 10.0, 15.0, "00:10-00:15", 0.0, 20.0),
        (2, 20.0, 30.0, "00:20-00:30", 20.0, 60.0),
    ]
    assert result.note.startswith(
        "The window crosses a scene cut at 00:20: frames 1-2 from scene 1, frames 3-5 from scene 2."
    )
    # What was seen is citable within each scene, never across the cut.
    assert spans_of(result) == [(10.0, 15.0), (20.0, 30.0)]
    assert [cell.scene for cell in analyzer.sequence_calls[0][2]] == [1, 1, 2, 2, 2]


def test_the_video_map_is_read_once_per_run() -> None:
    pool = FakePool(responses=[READY_STATE, SEGMENTS, CHAPTERS, CHAPTERS])
    deps = _deps(pool)

    _view(deps, 22.0, end_seconds=26.0)
    _view(deps, 10.0, end_seconds=30.0)

    assert sum("video_visual_segments" in statement for statement in pool.statements) == 1


# --- no index -------------------------------------------------------------------------------


def test_before_the_index_is_ready_the_sequence_still_works_as_one_citable_stretch() -> None:
    source = FakeFrameSource()
    deps = _deps(not_ready_pool(), frame_source=source)

    result = _view(deps, 100.0, frame_count=6)

    assert source.calls[0]["times"] == [100.0, 102.0, 104.0, 106.0, 108.0, 110.0]
    assert all(frame.scene is None for frame in result.frames)
    assert [(s.scene, s.start_seconds, s.end_seconds, s.scene_start_seconds) for s in result.scenes] == [
        (None, 100.0, 110.0, None)
    ]
    assert "scenes are not known yet" in result.note
    assert "scene cut" not in result.note
    assert "runs 10 s, to 01:50" in result.note
    assert spans_of(result) == [(100.0, 110.0)]


# --- frame count, and calls that spend nothing ----------------------------------------------


@pytest.mark.parametrize(("asked", "looked_at"), [(20, MAX_FRAME_COUNT), (1, MIN_FRAME_COUNT)])
def test_a_frame_count_outside_the_grid_s_range_is_clamped_and_says_so(asked: int, looked_at: int) -> None:
    source = FakeFrameSource()

    result = _view(_deps(frame_source=source), 22.0, end_seconds=30.0, frame_count=asked)

    assert len(source.calls[0]["times"]) == looked_at
    assert f"{looked_at} frames were looked at" in result.note


@pytest.mark.parametrize(
    ("question", "options", "reason"),
    [("  ", {"end_seconds": 30.0}, "the question is empty"), ("Does he?", {"end_seconds": 20.0}, "ends before it starts")],
)
def test_a_call_that_cannot_look_spends_nothing(question: str, options: dict, reason: str) -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, 22.0, question, **options)

    assert reason in result.note
    assert source.calls == []
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (0, 0)


# --- failures and the budget ----------------------------------------------------------------


def test_frames_that_cannot_be_extracted_give_their_look_back() -> None:
    deps = _deps(frame_source=FakeFrameSource(FrameExtractionError("The video has no frame at 70.0 s")))

    result = _view(deps, 22.0, end_seconds=70.0)

    assert "could not be extracted" in result.note
    assert result.frames == []
    assert spans_of(result) == []
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (1, 0)


def test_a_failing_image_model_is_a_note_and_its_look_stays_spent() -> None:
    deps = _deps(analyzer=FakeImageAnalyzer(RuntimeError("provider down")))

    result = _view(deps, 10.0, end_seconds=30.0)

    assert result.note.endswith("The image model failed to look at the frames.")
    assert "scene cut" in result.note
    assert spans_of(result) == []
    assert deps.visual_budget.looks_used == 1


def test_fewer_observations_than_frames_still_returns_every_frame() -> None:
    result = _view(_deps(analyzer=FakeImageAnalyzer(answered=1)), 22.0, end_seconds=26.0, frame_count=2)

    assert [frame.observation for frame in result.frames] == [
        "Cell 1",
        "The image model gave no separate observation for this frame.",
    ]


def test_with_no_looks_left_nothing_is_extracted() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    for _ in range(MAX_LOOKS):
        deps.visual_budget.take_look()

    result = _view(deps, 22.0, end_seconds=30.0)

    assert result.note == "No looks are left in this answer's budget."
    assert source.calls == []
    assert spans_of(result) == []


def test_after_six_visual_calls_view_sequence_does_no_work_and_says_the_budget_is_spent() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    for _ in range(MAX_VISUAL_TOOL_CALLS):
        deps.visual_budget.start_tool_call()

    result = _view(deps, 22.0, end_seconds=30.0)

    assert isinstance(result, VisualBudgetSpent)
    assert result.budget_spent is True
    assert source.calls == []


# --- the image model's message --------------------------------------------------------------


def test_the_sequence_prompt_lists_every_frame_s_time_and_scene_and_where_the_cut_falls() -> None:
    cells = [SequenceCell(250.0, 1), SequenceCell(252.0, 1), SequenceCell(256.0, 2)]

    [text, image] = sequence_prompt("Does he pick up the cup?", b"grid", cells)

    assert text.splitlines() == [
        "Question: Does he pick up the cup?",
        "The image is a grid of 3 frames from 04:10 to 04:16, in time order, read left to right, "
        "then top to bottom: Frame 1 at 04:10 (scene 1), Frame 2 at 04:12 (scene 1), Frame 3 at 04:16 (scene 2).",
        "There is a cut between frame 2 and frame 3.",
    ]
    assert (image.data, image.media_type) == (b"grid", JPEG)


def test_the_sequence_prompt_says_when_the_scenes_are_not_known() -> None:
    [text, _] = sequence_prompt("What happens?", b"grid", [SequenceCell(10.0), SequenceCell(12.0)])

    assert "Frame 1 at 00:10, Frame 2 at 00:12." in text
    assert text.endswith("Where the video cuts from scene to scene is not known.")


# --- scenes in the video map ----------------------------------------------------------------


def _segment(index: int, start: float, end: float, kind: str) -> StoredVisualSegment:
    return StoredVisualSegment(f"s{index}", index, start, end, kind, ())


def test_a_scene_spans_text_changes_and_stops_at_cuts() -> None:
    video_map = VideoVisualMap(
        segments=(
            _segment(0, 0.0, 10.0, "video_start"),
            _segment(1, 10.0, 20.0, "text_change"),
            _segment(2, 20.0, 30.0, "scene_change"),
            _segment(3, 30.0, 40.0, "text_change"),
            _segment(4, 40.0, 50.0, "scene_change"),
        ),
        chapters=(),
    )

    assert video_map.scene_at(15.0) == (0.0, 20.0)
    assert video_map.scene_at(20.0) == (20.0, 40.0)
    assert video_map.scene_at(35.0) == (20.0, 40.0)
    assert video_map.scene_at(45.0) == (40.0, 50.0)
    assert VideoVisualMap(segments=(), chapters=()).scene_at(5.0) is None
