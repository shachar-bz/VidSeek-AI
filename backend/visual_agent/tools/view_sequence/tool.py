"""A Pydantic AI tool that shows the image model frames across a window as one grid.

It serves two purposes. One frame cannot show an action -- "picks up the cup" is a change between
frames -- so a sequence shows what happens across a window. And a window is a cheap way to find
where in it something is shown: a search's candidate moment, or a stretch the agent is unsure of,
is scanned at once, and the frames that show it tell the agent which moment or segment to cite or
look at closer. The tool spaces frames evenly across the window, lays them out as one timestamped
grid (`services/video_frames/grid.py`), and asks the image model about them. The grid costs one
image of the budget, whatever the number of frames in it.

With no end given, the window is the segment the start falls in. A window is never cut at a
scene cut: each frame is told which scene of the window it comes from, the result lists the
scenes, and the image model is told where the cuts fall, so it does not read a cut as movement.
Before the index is ready the scenes are not known, and the tool still works without them.
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
from backend.services.visual_search import VideoVisualMap

from ...image_analysis import SequenceCell
from ..budget_spent import BudgetSpent
from ..deps import VisualDeps
from .result import SequenceFrame, SequenceScene, ViewedSequence

# How many frames one grid holds: enough to see an action happen, and at most a 3x3 grid of
# cells small enough that the whole grid is one readable image.
DEFAULT_FRAME_COUNT = 6
MIN_FRAME_COUNT = 2
MAX_FRAME_COUNT = 9

# The window looked at when no end is given and the video's segments are not known.
WINDOW_WITHOUT_SEGMENTS_SECONDS = 10.0

# A segment's end is where the next one starts, so a window running to a segment's end stops
# this much before it to keep its last frame inside the segment.
SEGMENT_END_MARGIN_SECONDS = 0.5

# The one image a grid costs.
GRID_IMAGES = 1

logger = logging.getLogger(__name__)


async def view_sequence(
    ctx: RunContext[VisualDeps],
    start_seconds: float,
    question: str,
    end_seconds: float | None = None,
    frame_count: int = DEFAULT_FRAME_COUNT,
) -> ViewedSequence | BudgetSpent:
    """Look at frames spread across a window, as one grid, and say what they show and what happens.

    Two uses. For actions and events: one frame cannot show someone picking something up, or
    what changes after a door opens. And to find where something is shown inside a window: when
    a search gives a rough moment, or you are not sure which part of a stretch shows what you
    want, scan it here and see which frames show it, then cite those times or look closer with
    view_frames. The frames are spaced evenly from the start to the end, both included.
    The whole grid costs one image. Each frame says which scene of the window it comes from;
    when the window crosses a cut, a change across it is a new scene, not an action.

    Args:
        start_seconds: Where the window starts, in seconds from the beginning of the video.
        question: What to look for across the frames, as a full question.
        end_seconds: Where the window ends; leave out to look to the end of the segment the
            start falls in.
        frame_count: How many frames to spread across the window, 2 to 9; 6 by default.

    Returns:
        What the image model saw in each frame and its answer across them, and the scenes the
        frames come from.
    """
    deps = ctx.deps
    question = question.strip()
    start = max(float(start_seconds), 0.0)
    if not question:
        return ViewedSequence(
            note="Nothing was looked at, and no tool call was spent: the question is empty.",
            budget=deps.budget.remaining(),
        )
    if end_seconds is not None and float(end_seconds) <= start:
        return ViewedSequence(
            note="Nothing was looked at, and no tool call was spent: the window ends before it starts.",
            budget=deps.budget.remaining(),
        )
    if not deps.budget.start_tool_call():
        return BudgetSpent()

    notes = []
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

    if deps.budget.take_images(GRID_IMAGES) < GRID_IMAGES:
        return ViewedSequence(note="No images are left to look with.", budget=deps.budget.remaining())
    try:
        frames = await asyncio.to_thread(
            deps.frames().frames, deps.video_id, times, long_side=CELL_LONG_SIDE
        )
        grid = await asyncio.to_thread(build_frame_grid, frames)
    except (FrameExtractionError, VideoNotStoredError) as error:
        deps.budget.return_images(GRID_IMAGES)
        return ViewedSequence(note=f"The frames could not be extracted: {error}", budget=deps.budget.remaining())

    scene_ranges = _scene_ranges(video_map, times)
    cells = [
        SequenceCell(time_seconds=time_seconds, scene=_scene_number(scene_ranges, scene_range))
        for time_seconds, scene_range in zip(times, scene_ranges)
    ]
    scenes = _scenes(scene_ranges, times)
    if len(scenes) > 1:
        notes.insert(0, _cut_note(scenes, cells))
    try:
        analysis = await deps.analyzer().analyze_sequence(question, grid, cells)
    except Exception:
        # The grid was sent, so its image stays spent, as in view_frames.
        logger.exception("The image model failed to look at a sequence of %d frames", len(cells))
        return ViewedSequence(
            note=" ".join([*notes, "The image model failed to look at the frames."]),
            budget=deps.budget.remaining(),
        )
    if len(analysis.frames) != len(cells):
        logger.warning(
            "The image model gave %d observations for a sequence of %d frames",
            len(analysis.frames),
            len(cells),
        )

    # What the frames show can be cited from the first frame of a scene to its last; a moment
    # across a cut is two moments.
    for scene_times in _times_by_scene(cells):
        deps.record_span(scene_times[0], scene_times[-1])
    return ViewedSequence(
        start_seconds=times[0],
        end_seconds=times[-1],
        frames=[
            SequenceFrame(
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
        budget=deps.budget.remaining(),
    )


def _default_end(video_map: VideoVisualMap | None, start: float, notes: list[str]) -> float:
    """The end of the segment the start falls in, or a fixed window when segments are not known."""
    segment = video_map.segment_at(start) if video_map is not None else None
    if segment is None:
        end = start + WINDOW_WITHOUT_SEGMENTS_SECONDS
        notes.append(f"No end was given, so the window runs {WINDOW_WITHOUT_SEGMENTS_SECONDS:g} s, to {format_timestamp(end)}.")
        return end
    end = max(start, segment.end_seconds - SEGMENT_END_MARGIN_SECONDS)
    notes.append(f"No end was given, so the window runs to the end of its segment, {format_timestamp(end)}.")
    return end


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


def _scenes(scene_ranges: list[tuple[float, float] | None], times: list[float]) -> list[SequenceScene]:
    """Every scene the frames come from, with the times of the frames taken from it."""
    frame_times: dict[tuple[float, float], list[float]] = {}
    for time_seconds, scene_range in zip(times, scene_ranges):
        if scene_range is not None:
            frame_times.setdefault(scene_range, []).append(time_seconds)
    return [
        SequenceScene(
            scene=number,
            start_seconds=scene_start,
            end_seconds=scene_end,
            frames=_times_text(scene_times),
        )
        for number, ((scene_start, scene_end), scene_times) in enumerate(frame_times.items(), start=1)
    ]


def _times_by_scene(cells: list[SequenceCell]) -> list[list[float]]:
    """The frames' times, one list per scene; one list for all of them when scenes are not known."""
    grouped: dict[int | None, list[float]] = {}
    for cell in cells:
        grouped.setdefault(cell.scene, []).append(cell.time_seconds)
    return list(grouped.values())


def _cut_note(scenes: list[SequenceScene], cells: list[SequenceCell]) -> str:
    """Which frames come from which scene, and where the video cuts between them."""
    parts = []
    for scene in scenes:
        positions = [position for position, cell in enumerate(cells, start=1) if cell.scene == scene.scene]
        span = f"frame {positions[0]}" if len(positions) == 1 else f"frames {positions[0]}-{positions[-1]}"
        parts.append(f"{span} from scene {scene.scene}")
    cuts = ", ".join(format_timestamp(scene.start_seconds) for scene in scenes[1:])
    return (
        f"The window crosses a scene cut at {cuts}: {', '.join(parts)}. "
        "A change across a cut is a new scene, not an action."
    )


def _times_text(times: list[float]) -> str:
    """One time, or the first and last, as MM:SS."""
    if len(times) == 1:
        return format_timestamp(times[0])
    return f"{format_timestamp(times[0])}-{format_timestamp(times[-1])}"
