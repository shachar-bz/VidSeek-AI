"""A Pydantic AI tool that shows the agent itself a few frames, large.

Every other look goes through the image model and comes back as words. This one is for what
words lose: small text, a diagram's boxes and arrows, a face, a small object, or the very frame
the viewer paused on. Each frame is extracted from the stored video at `CLOSEUP_LONG_SIDE` and
returned as an image (`ToolReturn.content`), after a `Frame N at MM:SS` label, while the return
value lists the frames with their times, which the runner's citation check reads. The images
stay in the agent's context for the rest of the turn, which is one reason a call costs a whole
look; a look whose frames cannot be extracted is given back.
"""

from __future__ import annotations

import asyncio

from pydantic_ai import BinaryContent, RunContext, ToolReturn

from backend.services.video_frames import (
    FrameExtractionError,
    VideoNotStoredError,
    format_timestamp,
)

from ..deps import ConversationDeps
from ..visual_budget_spent import VisualBudgetSpent
from .result import CloseupFrame, CloseupFrames

# A close view is of a few exact moments, each a large image in the agent's own context.
MAX_FRAMES_PER_CALL = 3

# How large each frame is shown: about three times a grid cell on each side, enough to make out
# small text or a detail.
CLOSEUP_LONG_SIDE = 1024


async def view_frames_closeup(
    ctx: RunContext[ConversationDeps], times: list[float]
) -> ToolReturn | CloseupFrames | VisualBudgetSpent:
    """See 1-3 frames yourself, large. Costs one look.

    For small text, a diagram's boxes and arrows, a face, a small object, or the frame the
    viewer paused on. The frames come back as images after this result, each labelled with its
    number and time.

    Args:
        times: The exact times to see, in seconds from the beginning of the video; at most
            three. Repeated times are shown once.

    Returns:
        The frames shown, with their times and chapters, followed by the images.
    """
    deps = ctx.deps
    budget = deps.visual_budget
    wanted = list(dict.fromkeys(max(float(time_seconds), 0.0) for time_seconds in times))
    if not wanted:
        return CloseupFrames(
            note="Nothing was looked at, and no tool call was spent: no times were given.",
            budget=budget.remaining(),
        )
    if not budget.start_tool_call():
        return VisualBudgetSpent()
    notes = []
    if len(wanted) > MAX_FRAMES_PER_CALL:
        notes.append(f"Only the first {MAX_FRAMES_PER_CALL} times were looked at.")
        wanted = wanted[:MAX_FRAMES_PER_CALL]
    if not budget.take_look():
        return CloseupFrames(
            note=" ".join([*notes, "No looks are left in this answer's budget."]),
            budget=budget.remaining(),
        )
    try:
        frames = await asyncio.to_thread(
            deps.frames().frames, deps.video_id, wanted, long_side=CLOSEUP_LONG_SIDE
        )
    except (FrameExtractionError, VideoNotStoredError) as error:
        budget.return_look()
        return CloseupFrames(
            note=" ".join([*notes, f"The frames could not be extracted: {error}"]),
            budget=budget.remaining(),
        )

    shown = []
    images: list[str | BinaryContent] = []
    for position, frame in enumerate(frames, start=1):
        timestamp = format_timestamp(frame.time_seconds)
        shown.append(
            CloseupFrame(
                frame=position,
                time_seconds=frame.time_seconds,
                start_seconds=frame.time_seconds,
                end_seconds=frame.time_seconds,
                timestamp=timestamp,
                chapter=deps.chapter_at(frame.time_seconds),
            )
        )
        images.append(f"Frame {position} at {timestamp}")
        images.append(BinaryContent(data=frame.image_bytes, media_type=frame.media_type))
    return ToolReturn(
        return_value=CloseupFrames(frames=shown, note=" ".join(notes) or None, budget=budget.remaining()),
        content=images,
    )
