"""A Pydantic AI tool that finds the moments of the video by the text written on screen.

A thin door onto `services/visual_search/`: the stored OCR text of every keyframe is searched
by what it means (multilingual-e5-small) and, when words are given, for those exact strings.
The text was read there, so each moment is citable (`result.py`). A search spends one visual
tool call and no look.

The words are cleaned here before the service sees them -- blank ones dropped, the list cut to
the service's limit -- so a sloppy call still searches instead of failing. The search runs off
the event loop: the first query of a process loads the text encoder.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from backend.services.video_frames import format_timestamp
from backend.services.visual_search import INDEX_READY, MAX_WORDS, normalized
from backend.services.visual_search import search_screen_text as search_screen_text_in_video

from ..deps import ConversationDeps
from ..visual_budget_spent import VisualBudgetSpent
from ..visual_index_notes import unsearchable_note
from .result import ScreenTextMoment, ScreenTextMoments

logger = logging.getLogger(__name__)


async def search_screen_text(
    ctx: RunContext[ConversationDeps], query: str, words: list[str] | None = None
) -> ScreenTextMoments | VisualBudgetSpent:
    """Find moments by the text written on screen: slides, boards, signs, code. Costs no look.

    `query` finds text that means what it describes. `words` finds text that contains those
    exact strings, ignoring case and spaces; give the spellings it may be written in. Up to 5 of
    each, with a snippet of the text read there. OCR can misread handwriting and math. While OCR
    is still reading the video, an empty result does not mean the text isn't on screen.

    Args:
        query: What the text is about, in plain words in any language, e.g. "the formula for
            the derivative".
        words: Up to five words or short phrases expected to be written on screen, in the
            language they would be written in, e.g. ["kafka", "partitions"]. Leave out to
            search by meaning only.

    Returns:
        The moments found, exact-word matches first, and a note when nothing was searched or
        found, or OCR is still reading.
    """
    deps = ctx.deps
    budget = deps.visual_budget
    query = query.strip()
    if not query:
        return ScreenTextMoments(
            note="Nothing was searched, and no tool call was spent: the query is empty.",
            budget=budget.remaining(),
        )
    if not budget.start_tool_call():
        return VisualBudgetSpent()
    notes = []
    wanted = [word.strip() for word in words or [] if normalized(word)]
    if len(wanted) > MAX_WORDS:
        notes.append(f"Only the first {MAX_WORDS} words were looked for: {', '.join(wanted[:MAX_WORDS])}.")
        wanted = wanted[:MAX_WORDS]
    try:
        result = await asyncio.to_thread(
            search_screen_text_in_video, deps.video_id, query, wanted or None, pool=deps.pool
        )
    except Exception:
        logger.exception("The on-screen text search failed for video %s", deps.video_id)
        return ScreenTextMoments(
            note="The search failed. Look at the frames with view_sequence instead.", budget=budget.remaining()
        )
    if result.index_status != INDEX_READY:
        return ScreenTextMoments(note=" ".join([*notes, unsearchable_note(result)]), budget=budget.remaining())

    moments = [
        ScreenTextMoment(
            start_seconds=moment.start_seconds,
            end_seconds=moment.end_seconds,
            timestamp=f"{format_timestamp(moment.start_seconds)}-{format_timestamp(moment.end_seconds)}",
            chapter=moment.chapter.title if moment.chapter is not None else None,
            found_by=list(moment.found_by),
            matched_words=list(moment.matched_words),
            on_screen_text=moment.on_screen_text,
            shot_boundary=moment.segment.boundary_kind,
        )
        for moment in result.moments
    ]
    if not moments:
        notes.append("Nothing matched.")
    if result.ocr_pending:
        notes.append(
            f"OCR has not read the text of {result.unread_keyframe_count} keyframes yet, so text "
            "written there cannot be found yet: an empty result does not mean it is not on screen."
        )
    return ScreenTextMoments(moments=moments, note=" ".join(notes) or None, budget=budget.remaining())
