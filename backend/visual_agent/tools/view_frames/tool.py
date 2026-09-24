"""A Pydantic AI tool that shows frames of the video to the image model and returns what it saw.

The frames are extracted from the stored video on demand (`services/video_frames/`), in
parallel, and sent to the image model together with the sub-agent's question. The sub-agent
gets the model's words back, never the pixels. Each frame spends one image of the budget; the
images of a call that fails to extract are given back.
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

# The most frames one call looks at: as many as are extracted at once, and enough for an
# action spread across a short window.
MAX_FRAMES_PER_CALL = 6

logger = logging.getLogger(__name__)


async def view_frames(
    ctx: RunContext[VisualDeps], timestamps: list[float], question: str
) -> ViewedFrames | BudgetSpent:
    """Look at the frames shown at these times and say what they show, in answer to a question.

    The only way to know what a picture shows: objects, people, where things are, what a
    diagram means, what is happening. For an action, pass a few times spread across a short
    window. Each frame costs one image of the budget.

    Args:
        timestamps: The times to look at, in seconds from the beginning of the video; at most
            six. Repeated times are looked at once.
        question: What to look for in the frames, as a full question.

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
        frames = await asyncio.to_thread(deps.frames().frames, deps.video_id, times)
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
