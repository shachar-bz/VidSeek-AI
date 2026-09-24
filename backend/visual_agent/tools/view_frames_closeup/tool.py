"""A Pydantic AI tool that shows the image model a few frames large, for a detail a grid cell is too small to show.

`view_sequence` is the agent's usual look: a whole window as one grid of small cells, for one
image. This is the close look behind it: a few exact times, each frame extracted from the stored
video large (`CLOSEUP_LONG_SIDE`) and sent on its own, so a diagram's boxes, a face or a small
object can be made out. The sub-agent gets the model's words back, never the pixels. Each frame
spends one image of the budget; the images of a call that fails to extract are given back.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from backend.services.video_frames import (
    FrameExtractionError,
    VideoNotStoredError,
    format_timestamp,
)

from ..budget_spent import BudgetSpent
from ..deps import VisualDeps
from .result import ViewedFrame, ViewedFrames

# A close look is at a few exact moments; scanning a stretch is view_sequence's job, and each
# frame here costs one image of a small budget.
MAX_FRAMES_PER_CALL = 3

# How large each frame is sent: about three times a grid cell on each side, enough to make out
# a detail, while small print is left to read_frame_text, which reads larger still.
CLOSEUP_LONG_SIDE = 1024

logger = logging.getLogger(__name__)


async def view_frames_closeup(
    ctx: RunContext[VisualDeps], timestamps: list[float], question: str
) -> ViewedFrames | BudgetSpent:
    """Look closely at one to three frames, each shown large, and say what they show.

    For a detail too small to make out in a view_sequence grid: what a diagram's boxes and
    arrows say, a face, a small object, where exactly something is. Also for the one frame the
    viewer paused on, when that frame alone answers the question. Not for actions or for
    finding which part of a window shows something; view_sequence does both for one image.
    Written text is read better, and for free, by read_frame_text. Each frame costs one image.

    Args:
        timestamps: The exact times to look at, in seconds from the beginning of the video; at
            most three. Repeated times are looked at once.
        question: What to look for, as a full question that makes sense on its own: the image
            model sees only this question and the frames. Ask what is there ("What is on the
            table?"), not whether what you expect is there.

    Returns:
        What the image model saw in each frame, in order, and its answer across them.
    """
    deps = ctx.deps
    if not deps.budget.start_tool_call():
        return BudgetSpent()
    times = list(dict.fromkeys(max(float(time_seconds), 0.0) for time_seconds in timestamps))
    notes = []
    if len(times) > MAX_FRAMES_PER_CALL:
        notes.append(f"Only the first {MAX_FRAMES_PER_CALL} times were looked at.")
        times = times[:MAX_FRAMES_PER_CALL]
    granted = deps.budget.take_images(len(times))
    if granted < len(times):
        notes.append(
            "No images are left to look with." if granted == 0
            else f"Only {granted} images were left, so only the first {granted} times were looked at."
        )
        times = times[:granted]
    if not times:
        return ViewedFrames(note=" ".join(notes) or "No times were given.", budget=deps.budget.remaining())
    try:
        frames = await asyncio.to_thread(
            deps.frames().frames, deps.video_id, times, long_side=CLOSEUP_LONG_SIDE
        )
    except (FrameExtractionError, VideoNotStoredError) as error:
        deps.budget.return_images(len(times))
        return ViewedFrames(note=f"The frames could not be extracted: {error}", budget=deps.budget.remaining())
    try:
        analysis = await deps.analyzer().analyze(question, frames)
    except Exception:
        # The frames were sent, so their images stay spent. The agent is told rather than the
        # investigation failing: it may still answer from text it has already read.
        logger.exception("The image model failed to look at %d frames", len(frames))
        return ViewedFrames(note="The image model failed to look at the frames.", budget=deps.budget.remaining())
    if len(analysis.frames) != len(frames):
        logger.warning(
            "The image model gave %d observations for %d frames", len(analysis.frames), len(frames)
        )
    viewed = []
    for position, frame in enumerate(frames):
        deps.record_span(frame.time_seconds, frame.time_seconds)
        viewed.append(
            ViewedFrame(
                time_seconds=frame.time_seconds,
                timestamp=format_timestamp(frame.time_seconds),
                chapter=deps.chapter_at(frame.time_seconds),
                observation=(
                    analysis.frames[position] if position < len(analysis.frames)
                    else "The image model gave no separate observation for this frame."
                ),
            )
        )
    return ViewedFrames(
        frames=viewed,
        answer=analysis.answer,
        note=" ".join(notes) or None,
        budget=deps.budget.remaining(),
    )
