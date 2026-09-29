"""A Pydantic AI tool that checks scattered frames at once, on one contact sheet the image model reads.

The usual way to check what the searches found: picture hits and transcript times from anywhere
in the video go on one grid (`services/video_frames/grid.py`), each cell stamped with its time,
and the image model says for each whether the thing asked about is there, with a short
description of what it saw. It spends one visual tool call and one look, however many frames;
a look whose frames cannot be extracted is given back. Every frame shown is citable, as an
instant (`result.py`).
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from backend.services.video_frames import (
    FrameExtractionError,
    VideoNotStoredError,
    build_frame_grid,
    format_timestamp,
)
from backend.services.video_frames.grid import CELL_LONG_SIDE

from ...image_analysis import CandidateVerdict
from ..deps import ConversationDeps
from ..visual_budget_spent import VisualBudgetSpent
from .result import CandidateFrame, ViewedCandidates

# How many frames one sheet holds: a 3x2 grid of cells still large enough to judge each one.
MAX_CANDIDATES = 6

# What a frame the image model gave no verdict for comes back as.
MISSING_VERDICT = CandidateVerdict(
    description="The image model gave no verdict for this frame.", present="unclear"
)

logger = logging.getLogger(__name__)


async def view_candidates(
    ctx: RunContext[ConversationDeps], times: list[float], question: str
) -> ViewedCandidates | VisualBudgetSpent:
    """Check up to 6 frames from anywhere in the video at once, on one contact sheet. Costs one look.

    For each frame, the image model describes in 1-3 lines what is visible and says whether the
    thing in `question` is present: yes, no or unclear. Ask what one frame can show ("Is there a
    ball?"), since a single frame cannot show an action. The cells are small: for fine detail,
    use view_frames_closeup.

    Args:
        times: The frames to check, in seconds from the beginning of the video; at most six,
            in any order. Repeated times are checked once.
        question: What to check each frame for, as a full question that makes sense on its
            own: the image model sees only this question and the frames.

    Returns:
        Each frame's verdict and description, in the order the times were given.
    """
    deps = ctx.deps
    budget = deps.visual_budget
    question = question.strip()
    wanted = list(dict.fromkeys(max(float(time_seconds), 0.0) for time_seconds in times))
    if not wanted:
        return ViewedCandidates(
            note="Nothing was looked at, and no tool call was spent: no times were given.",
            budget=budget.remaining(),
        )
    if not question:
        return ViewedCandidates(
            note="Nothing was looked at, and no tool call was spent: the question is empty.",
            budget=budget.remaining(),
        )
    if not budget.start_tool_call():
        return VisualBudgetSpent()
    notes = []
    if len(wanted) > MAX_CANDIDATES:
        notes.append(f"Only the first {MAX_CANDIDATES} times were looked at.")
        wanted = wanted[:MAX_CANDIDATES]
    if not budget.take_look():
        return ViewedCandidates(
            note=" ".join([*notes, "No looks are left in this answer's budget."]),
            budget=budget.remaining(),
        )
    try:
        frames = await asyncio.to_thread(
            deps.frames().frames, deps.video_id, wanted, long_side=CELL_LONG_SIDE
        )
        grid = await asyncio.to_thread(build_frame_grid, frames)
    except (FrameExtractionError, VideoNotStoredError) as error:
        budget.return_look()
        return ViewedCandidates(
            note=" ".join([*notes, f"The frames could not be extracted: {error}"]),
            budget=budget.remaining(),
        )
    cell_times = [frame.time_seconds for frame in frames]
    try:
        analysis = await deps.analyzer().analyze_candidates(question, grid, cell_times)
    except Exception:
        # The sheet was sent, so its look stays spent. The agent is told rather than the run
        # failing: it may still answer from what it has already found.
        logger.exception("The image model failed to look at a contact sheet of %d frames", len(frames))
        return ViewedCandidates(
            note=" ".join([*notes, "The image model failed to look at the frames."]),
            budget=budget.remaining(),
        )
    if len(analysis.frames) != len(cell_times):
        logger.warning(
            "The image model gave %d verdicts for a contact sheet of %d frames",
            len(analysis.frames),
            len(cell_times),
        )

    looked_at = []
    for position, time_seconds in enumerate(cell_times):
        verdict = analysis.frames[position] if position < len(analysis.frames) else MISSING_VERDICT
        looked_at.append(
            CandidateFrame(
                frame=position + 1,
                time_seconds=time_seconds,
                start_seconds=time_seconds,
                end_seconds=time_seconds,
                timestamp=format_timestamp(time_seconds),
                chapter=deps.chapter_at(time_seconds),
                present=verdict.present,
                description=verdict.description,
            )
        )
    return ViewedCandidates(frames=looked_at, note=" ".join(notes) or None, budget=budget.remaining())
