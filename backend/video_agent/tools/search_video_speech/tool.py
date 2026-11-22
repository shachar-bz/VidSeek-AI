"""A Pydantic AI tool that finds the moments of the current video a question is about.

A thin door onto `services/memory_search.py`: every memory of the video is scored against the
query, and the ones that stand out from the rest of the video come back. Which ones stand out,
and how many come back, is the service's settings, not the model's to choose.
"""

from __future__ import annotations

from pydantic_ai import RunContext

from backend.services.memory_search import search_memories

from ..deps import ConversationDeps
from .result import MemorySearchHit, MemorySearchResult


def memories_semantic_search(ctx: RunContext[ConversationDeps], query: str) -> MemorySearchResult:
    """Find the moments of this video whose speech is closest in meaning to a question or topic.

    Call this whenever answering needs something that was said in the video and you do not
    already have it. Search by meaning, not by keyword: pass the question or topic in
    natural language rather than words you expect to appear verbatim.

    Every moment of the video is compared with the query. Only moments that stand out from
    the rest of this video are returned: up to 8, closest first. When none stands out, the
    note says so and the 3 closest moments come back marked `weak`: what they say is real,
    but probably not what was asked for. A search can miss a moment that is there: when what
    comes back does not answer, search again in other words, or read the chapter around it.

    Args:
        query: What to look for, in natural language.

    Returns:
        The moments found, closest first, each with what was said, when it was said, and
        the ids of the memory and chapter it belongs to, and a note when nothing stood out
        or the video has nothing to search.
    """
    found = search_memories(ctx.deps.video_id, query, pool=ctx.deps.pool)
    moments = [
        MemorySearchHit(
            memory_id=memory.memory_id,
            chapter_id=memory.chapter_id,
            chapter_title=memory.chapter_title,
            summary=memory.summary,
            text=memory.text,
            start_seconds=memory.start_seconds,
            end_seconds=memory.end_seconds,
            weak=found.nothing_stood_out,
        )
        for memory in found.memories
    ]
    note = None
    if not moments:
        note = "There was nothing to search: this video has no stored moments of what was said."
    elif found.nothing_stood_out:
        note = (
            "Nothing stood out for this query: these are only the closest moments, marked weak, "
            "and they are probably not what was asked for."
        )
    return MemorySearchResult(moments=moments, note=note)
