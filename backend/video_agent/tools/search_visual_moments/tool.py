"""A Pydantic AI tool that finds the frames of the video whose picture looks like a description.

A thin door onto `services/visual_search/`: every frame sampled every two seconds is scored
against the query with SigLIP 2, and the ones that stand out come back, one per shot. Nobody
sees the pixels here, so a frame found is a lead, not a finding, and nothing in the result is
citable (`result.py`). A search spends one visual tool call and no look.

The search runs off the event loop: the first query of a process loads the text encoder, and
every query scans the video's frame vectors.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from backend.services.video_frames import format_timestamp
from backend.services.visual_search import INDEX_READY
from backend.services.visual_search import search_visual_moments as search_moments_in_video

from ..deps import ConversationDeps
from ..visual_budget_spent import VisualBudgetSpent
from ..visual_index_notes import unsearchable_note
from .result import PictureMatch, PictureMatches

logger = logging.getLogger(__name__)


async def search_visual_moments(
    ctx: RunContext[ConversationDeps], query: str
) -> PictureMatches | VisualBudgetSpent:
    """Find frames whose picture looks like a description. Costs no look.

    Every frame sampled every 2 seconds is compared with the query. Only frames that stand out
    from the rest of this video are returned: at most one per shot, up to 6, best first. When
    nothing stands out, the note says so and the 3 closest frames come back marked `weak`. A hit
    means a frame resembles the query, not that it shows it: look at it before saying what it
    shows. Its times cannot be cited until you have. Describe what is visible ("a whiteboard
    with equations", "a ball on grass"), not what the user asked ("when is the ball in the air").

    Args:
        query: What is visible, described in plain words in any language.

    Returns:
        The frames found, best first, each with its shot and chapter, and a note when nothing
        was searched or nothing stood out.
    """
    deps = ctx.deps
    budget = deps.visual_budget
    query = query.strip()
    if not query:
        return PictureMatches(
            note="Nothing was searched, and no tool call was spent: the query is empty.",
            budget=budget.remaining(),
        )
    if not budget.start_tool_call():
        return VisualBudgetSpent()
    try:
        result = await asyncio.to_thread(search_moments_in_video, deps.video_id, query, pool=deps.pool)
    except Exception:
        logger.exception("The picture search failed for video %s", deps.video_id)
        return PictureMatches(
            note="The search failed. Look at the frames with view_sequence instead.", budget=budget.remaining()
        )
    if result.index_status != INDEX_READY:
        return PictureMatches(note=unsearchable_note(result), budget=budget.remaining())

    frames = [
        PictureMatch(
            frame_seconds=moment.frame_seconds,
            timestamp=format_timestamp(moment.frame_seconds),
            shot_start_seconds=moment.segment.start_seconds,
            shot_end_seconds=moment.segment.end_seconds,
            chapter=moment.chapter.title if moment.chapter is not None else None,
            score=round(moment.peak_z_score, 2),
            weak=moment.weak,
        )
        for moment in result.moments
    ]
    note = None
    if result.nothing_stood_out:
        note = (
            "Nothing stood out for this description: these are the closest frames, marked weak, "
            "and they probably do not show it."
            if frames
            else "Nothing stood out for this description, and there were no frames to show instead."
        )
    return PictureMatches(frames=frames, note=note, budget=budget.remaining())
