"""A Pydantic AI tool that finds the moments of the video showing what a query describes.

A thin door onto `services/visual_search/`: the search reads the picture of every sampled frame
and returns up to six moments, one per shot. A picture match says a frame resembles the query,
not what it shows, so such a moment comes back marked `needs_look` and is not citable until the
agent has looked at it (`searched_moments.py`).

The search runs off the event loop: the first query of a process loads the text encoders, and
every query scans the video's frame vectors. It costs no image.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from backend.services.visual_search import search_visual_moments as search_moments_in_video

from ..budget_spent import BudgetSpent
from ..deps import VisualDeps
from ..searched_moments import SearchedMoments, searched_moments

logger = logging.getLogger(__name__)


async def search_visual_moments(
    ctx: RunContext[VisualDeps],
    query: str,
) -> SearchedMoments | BudgetSpent:
    """Find the moments of the video that show what a query describes. Costs no image.

    Searches the whole video by the picture of a frame sampled every two seconds. Returns up to
    six moments, one per shot, each with its times and chapter. Describe what is visible. Every
    moment is marked needs_look: it resembles the query, which is not the same as showing it,
    and it cannot be cited until you have looked at it.

    Args:
        query: What is shown, described in plain words in any language, e.g. "a diagram of
            servers and a queue" or "a cup on the table".

    Returns:
        The moments found, best first, and a note when nothing could be searched or matched.
    """
    deps = ctx.deps
    query = query.strip()
    if not query:
        return SearchedMoments(
            note="Nothing was searched, and no tool call was spent: the query is empty.",
            budget=deps.budget.remaining(),
        )
    if not deps.budget.start_tool_call():
        return BudgetSpent()
    try:
        result = await asyncio.to_thread(search_moments_in_video, deps.video_id, query, pool=deps.pool)
    except Exception:
        logger.exception("The visual moment search failed for video %s", deps.video_id)
        return SearchedMoments(
            note="The search failed. Look at the frames with view_sequence instead.",
            budget=deps.budget.remaining(),
        )
    return searched_moments(deps, result, [])
