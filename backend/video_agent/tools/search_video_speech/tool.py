"""A Pydantic AI tool that finds the moments of the current video where something was said.

A thin door onto `services/memory_search.py`, a hybrid search: every memory of the video is
ranked both by meaning (e5 embeddings, cosine) and by the exact words it shares with the query
(BM25), the two rankings are fused, and the closest few come back. How many come back is the
service's setting, not the model's to choose.
"""

from __future__ import annotations

from pydantic_ai import RunContext

from backend.services.memory_search import search_memories

from ..deps import ConversationDeps
from .result import MemorySearchHit, MemorySearchResult

NOTHING_TO_SEARCH_NOTE = "There was nothing to search: this video has no stored moments of what was said."


def search_video_speech(ctx: RunContext[ConversationDeps], query: str) -> MemorySearchResult:
    """Find the moments of this video where what was said is closest to a question or topic.

    Call this whenever answering needs something that was said in the video and you do not
    already have it. The search matches both by meaning and by the exact words used, so
    names, terms and numbers count: pass the question or topic in natural language, and
    include any specific terms it involves.

    It always returns up to 6 of the closest moments, closest first, even when none of them
    is about what was asked: judge each by what it says. When what comes back does not
    answer, search again in other words, or read the chapter around a moment.

    Args:
        query: What to look for, in natural language, with any specific terms.

    Returns:
        The closest moments, closest first, each with what was said, when it was said, and
        the ids of the memory and chapter it belongs to, and a note when the video has
        nothing to search.
    """
    memories = search_memories(ctx.deps.video_id, query, pool=ctx.deps.pool)
    moments = [
        MemorySearchHit(
            memory_id=memory.memory_id,
            chapter_id=memory.chapter_id,
            chapter_title=memory.chapter_title,
            summary=memory.summary,
            text=memory.text,
            start_seconds=memory.start_seconds,
            end_seconds=memory.end_seconds,
        )
        for memory in memories
    ]
    note = None if moments else NOTHING_TO_SEARCH_NOTE
    return MemorySearchResult(moments=moments, note=note)
