"""A Pydantic AI tool that shows the image model frames across a window as one grid.

One frame cannot show an action -- "picks up the cup" is a change between frames -- so a
sequence shows what happens across a window, and where inside a shot something appears. The
tool spaces frames evenly across the window, lays them out as one timestamped grid
(`services/video_frames/grid.py`), and asks the image model about them. It spends one visual
tool call and one look, whatever the number of frames; a look whose frames cannot be extracted
is given back.

With no end given, the window runs from the start to the end of the shot (segment) it falls in,
or a fixed stretch when that is too short to look across. A window of one instant -- a search's
single-frame hit passed as it came -- is widened either side rather than refused, since a search
is accurate only to about one sample. A window is never cut at a scene cut: each frame is told
which scene of the window it comes from, the result lists the scenes, and the image model is
told where the cuts fall, so it does not read a cut as movement. Before the index is ready the
scenes are not known, and the tool still works without them.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from backend.services.video_frames import (
    FrameExtractionError,
    VideoNotStoredError,
    build_frame_grid,
    evenly_spaced_times,
    format_timestamp,
)
from backend.services.video_frames.grid import CELL_LONG_SIDE
from backend.services.visual_indexing import SAMPLE_INTERVAL_SECONDS
from backend.services.visual_search import VideoVisualMap

from ...image_analysis import SequenceCell
from ..deps import ConversationDeps
from ..visual_budget_spent import VisualBudgetSpent
from .result import SequenceFrame, SequenceScene, ViewedSequence

# How many frames one grid holds: enough to see an action happen, and at most a 3x3 grid of
# cells small enough that the whole grid is one readable image.
DEFAULT_FRAME_COUNT = 6
MIN_FRAME_COUNT = 2
MAX_FRAME_COUNT = 9

# The window looked at when no end is given and the video's segments are not known, or the
# segment ends too soon after the start to look across.
WINDOW_WITHOUT_SEGMENTS_SECONDS = 10.0

# The shortest stretch to its segment's end a window without an end still runs to; shorter,
# and the fixed window is used, crossing into the next segment, so the grid is not one frame.
SHORTEST_SEGMENT_WINDOW_SECONDS = 2.0

# How far either side a window of one instant is widened: a search hit is accurate to about one
# sample, so what it found may be that far from the time it names.
INSTANT_WIDENING_SECONDS = SAMPLE_INTERVAL_SECONDS

# A segment's end is where the next one starts, so a window running to a segment's end stops
# this much before it to keep its last frame inside the segment.
SEGMENT_END_MARGIN_SECONDS = 0.5

logger = logging.getLogger(__name__)


async def view_sequence(
    ctx: RunContext[ConversationDeps],
    start_seconds: float,
    question: str,
    end_seconds: float | None = None,
    frame_count: int = DEFAULT_FRAME_COUNT,
) -> ViewedSequence | VisualBudgetSpent:
    """Look at frames spread across one window, as one grid, and learn what happens across them. Costs one look.

    For actions, order, before and after, and where inside a shot something appears. The
    frames are spaced evenly from the start to the end, both included. With no end, the window
    runs to the end of the shot the start falls in. The image model reports frame by frame and
    says what changes across them. Frames from different scenes are marked; a change across a
    cut is not an action. Each cell is small: for a detail, use view_frames_closeup.

    Args:
        start_seconds: Where the window starts, in seconds from the beginning of the video.
        question: What to look for across the frames, as a full question that makes sense on
            its own: the image model sees only this question and the frames. Ask what is there,
            what happens or which frames show something ("Which frames show a cup, and where
            is it?"), not whether what you expect is there.
        end_seconds: Where the window ends; leave out to look to the end of the shot the start
            falls in. An end equal to the start is widened two seconds either side.
        frame_count: How many frames to spread across the window, 2 to 9; 6 by default.
            Fewer for a few seconds around one moment, more for a long stretch.

    Returns:
        What the image model saw in each frame and its answer across them, and the scenes the
        frames come from, each with the stretch of it the frames showed.
    """
    deps = ctx.deps
    budget = deps.visual_budget
    question = question.strip()
    start = max(float(start_seconds), 0.0)
    if not question:
        return ViewedSequence(
            note="Nothing was looked at, and no tool call was spent: the question is empty.",
            budget=budget.remaining(),
        )
    if end_seconds is not None and float(end_seconds) < start:
        return ViewedSequence(
            note="Nothing was looked at, and no tool call was spent: the window ends before it starts.",
            budget=budget.remaining(),
        )
    if not budget.start_tool_call():
        return VisualBudgetSpent()

    notes = []
    if end_seconds is not None and float(end_seconds) == start:
        start, end_seconds = _widened_instant(start, notes)
    count = min(max(int(frame_count), MIN_FRAME_COUNT), MAX_FRAME_COUNT)
    if count != frame_count:
        notes.append(f"{count} frames were looked at, since a grid holds {MIN_FRAME_COUNT} to {MAX_FRAME_COUNT}.")
    try:
        video_map = await asyncio.to_thread(deps.video_map)
    except Exception:
        logger.exception("The segments of video %s could not be read", deps.video_id)
        video_map = None
    if video_map is None:
        notes.append("The video's scenes are not known yet, so the frames carry no scene.")
    end = float(end_seconds) if end_seconds is not None else _default_end(video_map, start, notes)
    times = evenly_spaced_times(start, end, count)

    if not budget.take_look():
        return ViewedSequence(note="No looks are left in this answer's budget.", budget=budget.remaining())
    try:
        frames = await asyncio.to_thread(
            deps.frames().frames, deps.video_id, times, long_side=CELL_LONG_SIDE
        )
        grid = await asyncio.to_thread(build_frame_grid, frames)
    except (FrameExtractionError, VideoNotStoredError) as error:
        budget.return_look()
        return ViewedSequence(note=f"The frames could not be extracted: {error}", budget=budget.remaining())

    scene_ranges = _scene_ranges(video_map, times)
    cells = [
        SequenceCell(time_seconds=time_seconds, scene=_scene_number(scene_ranges, scene_range))
        for time_seconds, scene_range in zip(times, scene_ranges)
    ]
    scenes = _scenes(scene_ranges, cells)
    numbered_scenes = [scene for scene in scenes if scene.scene is not None]
    if len(numbered_scenes) > 1:
        notes.insert(0, _cut_note(numbered_scenes, cells))
    try:
        analysis = await deps.analyzer().analyze_sequence(question, grid, cells)
    except Exception:
        # The grid was sent, so its look stays spent. The agent is told rather than the run
        # failing: it may still answer from what it has already found.
        logger.exception("The image model failed to look at a sequence of %d frames", len(cells))
        return ViewedSequence(
            note=" ".join([*notes, "The image model failed to look at the frames."]),
            budget=budget.remaining(),
        )
    if len(analysis.frames) != len(cells):
        logger.warning(
            "The image model gave %d observations for a sequence of %d frames",
            len(analysis.frames),
            len(cells),
        )

    return ViewedSequence(
        first_frame_seconds=times[0],
        last_frame_seconds=times[-1],
        frames=[
            SequenceFrame(
                frame=position + 1,
                time_seconds=cell.time_seconds,
                timestamp=format_timestamp(cell.time_seconds),
                scene=cell.scene,
                chapter=deps.chapter_at(cell.time_seconds),
                observation=(
                    analysis.frames[position] if position < len(analysis.frames)
                    else "The image model gave no separate observation for this frame."
                ),
            )
            for position, cell in enumerate(cells)
        ],
        scenes=scenes,
        answer=analysis.answer,
        note=" ".join(notes) or None,
        budget=budget.remaining(),
    )


def _default_end(video_map: VideoVisualMap | None, start: float, notes: list[str]) -> float:
    """The end of the segment the start falls in, or a fixed window when segments are not known."""
    segment = video_map.segment_at(start) if video_map is not None else None
    if segment is None:
        end = start + WINDOW_WITHOUT_SEGMENTS_SECONDS
        notes.append(f"No end was given, so the window runs {WINDOW_WITHOUT_SEGMENTS_SECONDS:g} s, to {format_timestamp(end)}.")
        return end
    end = segment.end_seconds - SEGMENT_END_MARGIN_SECONDS
    if end - start < SHORTEST_SEGMENT_WINDOW_SECONDS:
        end = start + WINDOW_WITHOUT_SEGMENTS_SECONDS
        notes.append(
            "No end was given, and its shot ends too soon after the start, so the window runs "
            f"{WINDOW_WITHOUT_SEGMENTS_SECONDS:g} s, to {format_timestamp(end)}."
        )
        return end
    notes.append(f"No end was given, so the window runs to the end of its shot, {format_timestamp(end)}.")
    return end


def _widened_instant(time_seconds: float, notes: list[str]) -> tuple[float, float]:
    """A window of one instant widened either side, so the grid looks around what a search named."""
    start = max(time_seconds - INSTANT_WIDENING_SECONDS, 0.0)
    end = time_seconds + INSTANT_WIDENING_SECONDS
    notes.append(
        f"The window was one instant, so it was widened to {format_timestamp(start)}-{format_timestamp(end)}."
    )
    return start, end


def _scene_ranges(
    video_map: VideoVisualMap | None, times: list[float]
) -> list[tuple[float, float] | None]:
    """The scene each time falls in, as its start and end; None for every time with no segments."""
    if video_map is None:
        return [None for _ in times]
    return [video_map.scene_at(time_seconds) for time_seconds in times]


def _scene_number(
    scene_ranges: list[tuple[float, float] | None], scene_range: tuple[float, float] | None
) -> int | None:
    """The scene's number within the window, from 1, in the order the scenes are shown."""
    if scene_range is None:
        return None
    known = list(dict.fromkeys(found for found in scene_ranges if found is not None))
    return known.index(scene_range) + 1


def _scenes(
    scene_ranges: list[tuple[float, float] | None], cells: list[SequenceCell]
) -> list[SequenceScene]:
    """Every scene the frames come from, with the stretch of it they showed.

    Frames whose scene is not known make one entry of their own, with no scene: what they
    showed is still citable, from the first of them to the last.
    """
    grouped: dict[tuple[float, float] | None, list[SequenceCell]] = {}
    for cell, scene_range in zip(cells, scene_ranges):
        grouped.setdefault(scene_range, []).append(cell)
    return [
        SequenceScene(
            scene=scene_cells[0].scene,
            start_seconds=scene_cells[0].time_seconds,
            end_seconds=scene_cells[-1].time_seconds,
            frames=_times_text([cell.time_seconds for cell in scene_cells]),
            scene_start_seconds=scene_range[0] if scene_range is not None else None,
            scene_end_seconds=scene_range[1] if scene_range is not None else None,
        )
        for scene_range, scene_cells in grouped.items()
    ]


def _cut_note(scenes: list[SequenceScene], cells: list[SequenceCell]) -> str:
    """Which frames come from which scene, and where the video cuts between them."""
    parts = []
    for scene in scenes:
        positions = [position for position, cell in enumerate(cells, start=1) if cell.scene == scene.scene]
        span = f"frame {positions[0]}" if len(positions) == 1 else f"frames {positions[0]}-{positions[-1]}"
        parts.append(f"{span} from scene {scene.scene}")
    cuts = ", ".join(format_timestamp(scene.scene_start_seconds) for scene in scenes[1:])
    return (
        f"The window crosses a scene cut at {cuts}: {', '.join(parts)}. "
        "A change across a cut is a new scene, not an action."
    )


def _times_text(times: list[float]) -> str:
    """One time, or the first and last, as MM:SS."""
    if len(times) == 1:
        return format_timestamp(times[0])
    return f"{format_timestamp(times[0])}-{format_timestamp(times[-1])}"
