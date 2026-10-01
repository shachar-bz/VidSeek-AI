"""A Pydantic AI tool that reads one whole chapter of the current video."""

from __future__ import annotations

from pydantic_ai import RunContext

from backend.core.errors import ChapterNotFoundError
from backend.storage.postgres import PostgresChapters

from ..deps import ConversationDeps
from .result import ChapterContext, ChapterMemory


def get_chapter_context(ctx: RunContext[ConversationDeps], chapter_id: str) -> ChapterContext:
    """Read a whole chapter of this video: what it covers, and every moment in it in order.

    Call this when a single moment is not enough to answer with -- to see what surrounded
    it, how a topic developed, or what a section of the video covers as a whole. Chapter
    ids come from `get_video_outline`, or from the moments `memories_semantic_search`
    returns.

    Every moment in the chapter is returned, however many there are, each as a one-line
    summary and its timing, never as what was said. For the words of one of these moments,
    call `get_memory_context` with its memory id and context_range=0; to find where a topic
    is discussed, use `memories_semantic_search`.

    Args:
        chapter_id: The id of the chapter to read, as given by a moment that belongs to it.

    Returns:
        The chapter's title, summary and timing, and its moments earliest first, each with
        its memory id.

    Raises:
        ChapterNotFoundError: This video has no chapter with that id.
    """
    stored = PostgresChapters(ctx.deps.pool).chapter_with_memories(ctx.deps.video_id, chapter_id)
    if stored is None:
        raise ChapterNotFoundError(chapter_id)
    return ChapterContext(
        chapter_id=stored.chapter_id,
        chapter_index=stored.chapter_index,
        title=stored.title,
        summary=stored.summary,
        start_seconds=stored.start_seconds,
        end_seconds=stored.end_seconds,
        memories=[
            ChapterMemory(
                memory_id=memory.memory_id,
                summary=memory.summary,
                start_seconds=memory.start_seconds,
                end_seconds=memory.end_seconds,
            )
            for memory in stored.memories
        ],
    )
