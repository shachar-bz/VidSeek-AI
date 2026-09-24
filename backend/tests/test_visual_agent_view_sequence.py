"""Tests for the visual sub-agent's view_sequence tool, and the scenes and prompt it relies on.

The tool is called directly with a real VisualDeps. The index state, segments and chapters come
from a `FakePool` answering reads in order -- the state, the segments, the chapters of the video
map, then the chapter outline `chapter_at` reads. The frame source hands back small real JPEGs,
so the grid is really built; the image analyzer is a stand-in that records what it was sent.
"""

import asyncio
import io

import pytest
from PIL import Image

from backend.services.video_frames import JPEG, ExtractedFrame, FrameExtractionError
from backend.services.video_frames.grid import CELL_LONG_SIDE
from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.services.visual_search import VideoVisualMap
from backend.storage.postgres import StoredVisualSegment
from backend.tests.fake_postgres import FakePool
from backend.visual_agent.budget import MAX_IMAGES, MAX_TOOL_CALLS
from backend.visual_agent.image_analysis import FrameAnalysis, SequenceCell, sequence_prompt
from backend.visual_agent.tools.budget_spent import BudgetSpent
from backend.visual_agent.tools.deps import VisualDeps
from backend.visual_agent.tools.view_sequence import (
    MAX_FRAME_COUNT,
    MIN_FRAME_COUNT,
    ViewedSequence,
    view_sequence,
)

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

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


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (200, 50, 50)).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeRunContext:
    """The single attribute the tools read off a RunContext."""

    def __init__(self, deps: VisualDeps):
        self.deps = deps


class FakeFrameSource:
    """Hands back a small JPEG per time asked for, or fails the way extraction fails."""

    def __init__(self, failure: Exception | None = None):
        self.failure = failure
        self.calls: list[dict] = []

    def frames(self, video_id, times, *, long_side=512, lossless=False):
        self.calls.append({"video_id": video_id, "times": list(times), "long_side": long_side})
        if self.failure is not None:
            raise self.failure
        return [ExtractedFrame(time_seconds=time, image_bytes=_jpeg(), media_type=JPEG) for time in times]


class FakeSequenceAnalyzer:
    """Says what each cell shows, or fails the way a model call fails."""

    def __init__(self, failure: Exception | None = None):
        self.failure = failure
        self.calls: list[tuple[str, bytes, list[SequenceCell]]] = []

    async def analyze(self, question, frames):
        raise AssertionError("view_sequence sends a grid, not separate frames")

    async def analyze_sequence(self, question, grid_jpeg, cells):
        self.calls.append((question, grid_jpeg, list(cells)))
        if self.failure is not None:
            raise self.failure
        return FrameAnalysis(
            frames=[f"Cell {position}" for position in range(1, len(cells) + 1)],
            answer="He picks up the cup.",
        )


def ready_pool() -> FakePool:
    return FakePool(responses=[READY_STATE, SEGMENTS, CHAPTERS, CHAPTERS])


def not_ready_pool() -> FakePool:
    return FakePool(responses=[INDEXING_STATE, CHAPTERS])


def _deps(
    pool: FakePool | None = None,
    *,
    frame_source: FakeFrameSource | None = None,
    analyzer: FakeSequenceAnalyzer | None = None,
) -> VisualDeps:
    return VisualDeps(
        video_id=VIDEO_ID,
        current_time_seconds=25.0,
        pool=pool or ready_pool(),
        frame_source=frame_source or FakeFrameSource(),
        image_analyzer=analyzer or FakeSequenceAnalyzer(),
    )


def _view(deps: VisualDeps, start: float, question: str = "Does he pick up the cup?", **options):
    return asyncio.run(view_sequence(FakeRunContext(deps), start, question, **options))


# --- one scene ------------------------------------------------------------------------------


def test_a_window_inside_one_scene_is_one_grid_costing_one_image() -> None:
    source, analyzer = FakeFrameSource(), FakeSequenceAnalyzer()
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
    assert (result.start_seconds, result.end_seconds) == (22.0, 32.0)
    # A slide change at 40 s is not a cut: the scene runs on to 60 s.
    assert [(s.scene, s.start_seconds, s.end_seconds, s.frames) for s in result.scenes] == [
        (1, 20.0, 60.0, "00:22-00:32")
    ]
    assert result.answer == "He picks up the cup."
    assert result.note is None
    assert deps.spans == [(22.0, 32.0)]
    assert (deps.budget.tool_calls_used, deps.budget.images_used) == (1, 1)
    assert result.budget == f"{MAX_TOOL_CALLS - 1} tool calls and {MAX_IMAGES - 1} images left."
    # Frames are extracted at the grid's cell size, and the image model gets one JPEG grid.
    assert source.calls[0]["long_side"] == CELL_LONG_SIDE
    [(question, grid, cells)] = analyzer.calls
    assert question == "Does he pick up the cup?"
    assert Image.open(io.BytesIO(grid)).format == "JPEG"
    assert [cell.scene for cell in cells] == [1] * 6


def test_with_no_end_the_window_runs_to_the_end_of_the_start_s_segment() -> None:
    source = FakeFrameSource()

    result = _view(_deps(frame_source=source), 22.0, frame_count=3)

    assert source.calls[0]["times"] == [22.0, 30.75, 39.5]
    assert "to the end of its segment, 00:39" in result.note


# --- scene cuts -----------------------------------------------------------------------------


def test_a_window_across_a_cut_is_not_cut_but_says_which_frames_come_from_which_scene() -> None:
    analyzer = FakeSequenceAnalyzer()
    deps = _deps(analyzer=analyzer)

    result = _view(deps, 10.0, end_seconds=30.0, frame_count=5)

    assert [(f.time_seconds, f.scene) for f in result.frames] == [(10.0, 1), (15.0, 1), (20.0, 2), (25.0, 2), (30.0, 2)]
    assert [(s.scene, s.start_seconds, s.end_seconds, s.frames) for s in result.scenes] == [
        (1, 0.0, 20.0, "00:10-00:15"),
        (2, 20.0, 60.0, "00:20-00:30"),
    ]
    assert result.note.startswith(
        "The window crosses a scene cut at 00:20: frames 1-2 from scene 1, frames 3-5 from scene 2."
    )
    # What was seen is citable within each scene, never across the cut.
    assert deps.spans == [(10.0, 15.0), (20.0, 30.0)]
    assert [cell.scene for cell in analyzer.calls[0][2]] == [1, 1, 2, 2, 2]


def test_the_video_map_is_read_once_per_investigation() -> None:
    pool = FakePool(responses=[READY_STATE, SEGMENTS, CHAPTERS, CHAPTERS])
    deps = _deps(pool)

    _view(deps, 22.0, end_seconds=26.0)
    _view(deps, 10.0, end_seconds=30.0)

    assert sum("video_visual_segments" in statement for statement in pool.statements) == 1


# --- no index -------------------------------------------------------------------------------


def test_before_the_index_is_ready_the_sequence_still_works_without_scenes() -> None:
    source = FakeFrameSource()
    deps = _deps(not_ready_pool(), frame_source=source)

    result = _view(deps, 100.0, frame_count=6)

    assert source.calls[0]["times"] == [100.0, 102.0, 104.0, 106.0, 108.0, 110.0]
    assert all(frame.scene is None for frame in result.frames)
    assert result.scenes == []
    assert "scenes are not known yet" in result.note
    assert "runs 10 s, to 01:50" in result.note
    assert deps.spans == [(100.0, 110.0)]


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
    assert (deps.budget.tool_calls_used, deps.budget.images_used) == (0, 0)


# --- failures and the budget ----------------------------------------------------------------


def test_frames_that_cannot_be_extracted_give_their_image_back() -> None:
    deps = _deps(frame_source=FakeFrameSource(FrameExtractionError("The video has no frame at 70.0 s")))

    result = _view(deps, 22.0, end_seconds=70.0)

    assert "could not be extracted" in result.note
    assert result.frames == []
    assert deps.spans == []
    assert (deps.budget.tool_calls_used, deps.budget.images_used) == (1, 0)


def test_a_failing_image_model_is_a_note_and_its_image_stays_spent() -> None:
    deps = _deps(analyzer=FakeSequenceAnalyzer(RuntimeError("provider down")))

    result = _view(deps, 10.0, end_seconds=30.0)

    assert result.note.endswith("The image model failed to look at the frames.")
    assert "scene cut" in result.note
    assert deps.spans == []
    assert deps.budget.images_used == 1


def test_with_no_images_left_nothing_is_extracted() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    deps.budget.take_images(MAX_IMAGES)

    result = _view(deps, 22.0, end_seconds=30.0)

    assert result.note == "No images are left to look with."
    assert source.calls == []


def test_after_six_calls_view_sequence_does_no_work_and_says_the_budget_is_spent() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    for _ in range(MAX_TOOL_CALLS):
        deps.budget.start_tool_call()

    assert isinstance(_view(deps, 22.0, end_seconds=30.0), BudgetSpent)
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
