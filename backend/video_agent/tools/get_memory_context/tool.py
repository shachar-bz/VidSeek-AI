"""A Pydantic AI tool that reads one memory of the current video together with its neighbours."""

from __future__ import annotations

from uuid import UUID

from pydantic_ai import ModelRetry, RunContext

from backend.storage.postgres import (
    ChapterHeading,
    ChapterWithNeighbours,
    PostgresChapters,
    PostgresMemories,
    StoredMemory,
)

from ..deps import ConversationDeps
from .result import BoundaryReason, ChapterBoundary, ContextMemory, MemoryContext

# How much context one call gives when the model does not say. One memory each side is
# enough to see what a moment was answering and where it led, which is what most questions
# about a search hit need; walking further is another call.
DEFAULT_CONTEXT_RANGE = 1

# The most a single call will read from each side, however much was asked for. A chapter is
# already bounded, but nothing bounds how long one chapter is, and a model that asks for a
# hundred memories should not be able to spend the whole conversation's context on one
# lookup. Over-large requests are clamped rather than refused: the call still answers, and
# `context_range_used` is how the result says the request was reduced.
MAX_CONTEXT_RANGE = 10


def get_memory_context(
    ctx: RunContext[ConversationDeps],
    memory_id: str,
    context_range: int = DEFAULT_CONTEXT_RANGE,
) -> MemoryContext:
    """Read a memory of this video together with the memories around it in the same chapter.

    Call this when you have a memory id, from a search or from an earlier lookup, and need
    what was said around it to understand it: what led up to a moment, or what followed it.
    Context never crosses into another chapter; when a side runs out, the result names the
    chapter beyond it so you can follow the thread there.

    Args:
        memory_id: The id of the memory to read around.
        context_range: How many memories to read on each side of it. Each side is bounded
            independently, so a side that runs out of chapter does not make the other side
            any shorter. Clamped to at most 10.

    Returns:
        The memory, the memories either side of it within its chapter, and, for each side
        that was cut short, why it stopped and which chapter lies beyond.

    Raises:
        ModelRetry: No memory of this video has that id.
    """
    resolved_range = _clamp(context_range)
    target = _load_target(ctx, memory_id)

    if target.chapter_id is None:
        return _ungrouped_context(target, resolved_range)

    chapter = PostgresChapters(ctx.deps.pool).with_neighbours(ctx.deps.video_id, target.chapter_id)
    window = PostgresMemories(ctx.deps.pool).chapter_window(
        target.chapter_id,
        target.memory_index - resolved_range,
        target.memory_index + resolved_range,
    )
    before = [memory for memory in window if memory.memory_index < target.memory_index]
    after = [memory for memory in window if memory.memory_index > target.memory_index]

    return MemoryContext(
        chapter_id=target.chapter_id,
        chapter_title=chapter.chapter.title if chapter else None,
        chapter_summary=chapter.chapter.summary if chapter else None,
        context_range_used=resolved_range,
        target=_as_context_memory(target),
        before=[_as_context_memory(memory) for memory in before],
        after=[_as_context_memory(memory) for memory in after],
        before_boundary=_boundary_if_clipped(
            len(before), resolved_range, "chapter_start", _side(chapter, "preceding")
        ),
        after_boundary=_boundary_if_clipped(
            len(after), resolved_range, "chapter_end", _side(chapter, "following")
        ),
    )


def _clamp(context_range: int) -> int:
    """The range this call will actually use.

    Zero is a legitimate request, meaning "just this memory", so the floor is zero rather
    than one. A negative range is nonsense the model can only have produced by mistake, and
    is clamped the same way an over-large one is instead of failing the call.
    """
    return max(0, min(context_range, MAX_CONTEXT_RANGE))


def _load_target(ctx: RunContext[ConversationDeps], memory_id: str) -> StoredMemory:
    """The memory the model asked about, or a retry telling it the id is not one of ours.

    The lookup is scoped to `ctx.deps.video_id`, the same way `memories_semantic_search` is,
    so the agent cannot read a video the conversation is not about. A malformed id, an id
    that exists in no video, and an id belonging to a different video are answered
    identically on purpose: all three mean the model invented or mixed up an id, and all
    three are fixed the same way, by going back to a search for a real one.
    """
    try:
        UUID(memory_id)
    except ValueError:
        target = None
    else:
        target = PostgresMemories(ctx.deps.pool).get(ctx.deps.video_id, memory_id)
    if target is None:
        raise ModelRetry(
            f"No memory of this video has the id {memory_id!r}. "
            "Search the video's memories to get an id that exists."
        )
    return target


def _ungrouped_context(target: StoredMemory, resolved_range: int) -> MemoryContext:
    """The result for a memory no chapter has been built around yet.

    Context is bounded by a chapter, so a memory without one has none to give. That is a
    state of the pipeline rather than a failure, since memories are produced before the
    chapter-grouping stage runs, so it answers with the memory itself and says on both sides
    why nothing came with it.
    """
    boundary = ChapterBoundary(reason="memory_not_grouped") if resolved_range > 0 else None
    return MemoryContext(
        chapter_id=None,
        chapter_title=None,
        chapter_summary=None,
        context_range_used=resolved_range,
        target=_as_context_memory(target),
        before=[],
        after=[],
        before_boundary=boundary,
        after_boundary=boundary,
    )


def _side(chapter: ChapterWithNeighbours | None, attribute: str) -> ChapterHeading | None:
    """The chapter on one side of the target's chapter, if the target's chapter was found."""
    return getattr(chapter, attribute) if chapter else None


def _boundary_if_clipped(
    returned: int, requested: int, reason: BoundaryReason, neighbour: ChapterHeading | None
) -> ChapterBoundary | None:
    """A boundary for one side, or None when that side gave everything that was asked for.

    Clipping is the only trigger: a range that happens to end exactly on the chapter's last
    memory lost nothing, and reporting a boundary there would tell the model something was
    withheld when nothing was.
    """
    if returned >= requested:
        return None
    return ChapterBoundary(
        reason=reason,
        chapter_id=neighbour.chapter_id if neighbour else None,
        chapter_title=neighbour.title if neighbour else None,
        chapter_summary=neighbour.summary if neighbour else None,
    )


def _as_context_memory(memory: StoredMemory) -> ContextMemory:
    """One stored memory as the agent receives it, without its index into the video."""
    return ContextMemory(
        memory_id=memory.memory_id,
        chapter_id=memory.chapter_id,
        text=memory.text,
        summary=memory.summary,
        start_seconds=memory.start_seconds,
        end_seconds=memory.end_seconds,
    )
