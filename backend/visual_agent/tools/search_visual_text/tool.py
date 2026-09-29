"""A Pydantic AI tool that finds the moments of the video whose on-screen text contains given words.

A thin door onto `services/visual_search/`: each word is looked for in every keyframe's OCR text
as a sequence of characters, with case and whitespace ignored (VISUAL_UNDERSTANDING_PLAN.md
§5.2). Moments come back ordered by how many different words they show, at most five. An OCR
misreading is not found.

The words are cleaned here before the service sees them -- blank ones dropped, the list cut to
the service's limit -- so a sloppy call still searches instead of failing. It costs no image.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from backend.services.visual_search import MAX_WORDS, normalized
from backend.services.visual_search import search_visual_text as search_text_in_video

from ..budget_spent import BudgetSpent
from ..deps import VisualDeps
from ..searched_moments import SearchedMoments, searched_moments

logger = logging.getLogger(__name__)


async def search_visual_text(
    ctx: RunContext[VisualDeps],
    words: list[str],
) -> SearchedMoments | BudgetSpent:
    """Find the moments where any of these words is written on screen. Costs no image.

    Each word is matched as a run of characters, ignoring case and spaces but not punctuation
    or digits ("e-mail" does not find "email"), and also inside longer words ("cup" finds
    "cupboard"); give the spellings it may be written in. Returns up to five moments, the ones
    showing the most different words first, each saying which words it matched. The words need
    not be the question's: a slide's title or a label near what is asked about can mark its
    moment. A word OCR misread is not found.

    Args:
        words: One to five words or short phrases you expect to be written on screen, in the
            language they would be written in, e.g. ["kafka", "partitions"].

    Returns:
        The moments found, and a note when nothing could be searched or matched.
    """
    deps = ctx.deps
    wanted = [word.strip() for word in words if normalized(word)]
    notes = []
    if not wanted:
        return SearchedMoments(
            note="Nothing was searched, and no tool call was spent: no words were given.",
            budget=deps.budget.remaining(),
        )
    if len(wanted) > MAX_WORDS:
        notes.append(f"Only the first {MAX_WORDS} words were looked for: {', '.join(wanted[:MAX_WORDS])}.")
        wanted = wanted[:MAX_WORDS]
    if not deps.budget.start_tool_call():
        return BudgetSpent()
    try:
        result = await asyncio.to_thread(search_text_in_video, deps.video_id, wanted, pool=deps.pool)
    except Exception:
        logger.exception("The visual text search failed for video %s", deps.video_id)
        return SearchedMoments(
            note="The search failed. Read the frames with read_frame_text instead.",
            budget=deps.budget.remaining(),
        )
    return searched_moments(deps, result, notes)
