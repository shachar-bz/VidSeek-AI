"""A Pydantic AI tool that finds the moments of the current video a question is about."""

from __future__ import annotations

from pydantic_ai import RunContext

from backend.services.embeddings.multilingual_text_embedding import MODEL_NAME, embed_query
from backend.storage.postgres import PostgresMemoryEmbeddings

from ..deps import ConversationDeps
from .result import MemorySearchHit

# How many moments one search answers with. A constant rather than an argument: the number
# is a property of how much video the agent can usefully read at once, which the model
# asking the question is not in a position to judge.
TOP_K = 5


def memories_semantic_search(ctx: RunContext[ConversationDeps], query: str) -> list[MemorySearchHit]:
    """Find the moments of this video whose content is closest to a question or topic.

    Call this whenever answering needs something that was said in the video and you do not
    already have it. Search by meaning, not by keyword: pass the question or topic in
    natural language rather than words you expect to appear verbatim.

    Args:
        query: What to look for, in natural language.

    Returns:
        Up to five moments, closest first, each with what was said, when it was said, and
        the ids of the memory and chapter it belongs to. Empty when the video has no
        searchable content.
    """
    store = PostgresMemoryEmbeddings(ctx.deps.pool)
    matches = store.nearest_memories(ctx.deps.video_id, embed_query(query), TOP_K, model=MODEL_NAME)
    return [
        MemorySearchHit(
            memory_id=match.memory_id,
            chapter_id=match.chapter_id,
            chapter_title=match.chapter_title,
            summary=match.summary,
            text=match.text,
            start_seconds=match.start_seconds,
            end_seconds=match.end_seconds,
        )
        for match in matches
    ]
