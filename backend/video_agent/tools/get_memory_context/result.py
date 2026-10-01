"""What one memory's surroundings look like to the agent that asked for them.

An envelope rather than a flat list of memories, because a flat list cannot say the three
things the agent needs alongside the text: which memory it asked about, which section it is
reading, and why a side stopped where it did. Pydantic AI serializes the result through these
models, but the model is not sent their schema: it sees field names and values only. So what
it must know to read the result, such as that an absent boundary means nothing was left out
and what each boundary reason means, is said in the tool's docstring, and the field
descriptions below document the code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Why one side of the window holds fewer memories than were asked for. `chapter_start` and
# `chapter_end` are the chapter's own edges; `memory_not_grouped` is the different case of
# a memory the chapter-grouping stage has not reached yet, which has no chapter to read
# around at all. A Literal rather than a sentence: a fixed set of states the tool's
# docstring can name, instead of prose the model would parse to find out which one it is in.
BoundaryReason = Literal["chapter_start", "chapter_end", "memory_not_grouped"]


class ChapterBoundary(BaseModel):
    """Why one side of the context stopped, and which chapter lies beyond it."""

    reason: BoundaryReason = Field(
        description=(
            "Why this side holds fewer memories than were asked for: 'chapter_start' or "
            "'chapter_end' when the chapter ran out, 'memory_not_grouped' when the memory "
            "has not been grouped into a chapter yet and so has no surroundings to read."
        )
    )
    chapter_id: str | None = Field(
        default=None,
        description=(
            "The id of the chapter on the far side of this boundary, which can be passed "
            "to a further lookup. Null when the video itself begins or ends here."
        ),
    )
    chapter_title: str | None = Field(
        default=None, description="The title of the chapter beyond this boundary, if there is one."
    )
    chapter_summary: str | None = Field(
        default=None,
        description="One line describing the chapter beyond this boundary, if there is one.",
    )


class ContextMemory(BaseModel):
    """One moment of the video, as it sits in its chapter."""

    memory_id: str = Field(description="The id of the memory this moment is stored as.")
    chapter_id: str | None = Field(
        default=None, description="The id of the chapter this moment belongs to, if it has one."
    )
    text: str = Field(description="What was actually said during this moment.")
    summary: str = Field(description="One line describing what this moment is about.")
    start_seconds: float = Field(
        description="When this moment starts, in seconds from the beginning of the video."
    )
    end_seconds: float = Field(
        description="When this moment ends, in seconds from the beginning of the video."
    )


class MemoryContext(BaseModel):
    """A memory together with the memories around it in the same chapter."""

    chapter_id: str | None = Field(
        default=None,
        description="The id of the chapter every memory here belongs to, if there is one.",
    )
    chapter_title: str | None = Field(
        default=None, description="The title of that chapter, if there is one."
    )
    chapter_summary: str | None = Field(
        default=None, description="One line describing that chapter, if there is one."
    )
    context_range_used: int = Field(
        description=(
            "How many memories each side was actually asked for, after the requested range "
            "was clamped to what one call may return. Compare with what you asked for to "
            "see whether the request was reduced."
        )
    )
    target: ContextMemory = Field(description="The memory that was asked about.")
    before: list[ContextMemory] = Field(
        default_factory=list,
        description="The memories immediately before the target, in the order they were spoken.",
    )
    after: list[ContextMemory] = Field(
        default_factory=list,
        description="The memories immediately after the target, in the order they were spoken.",
    )
    before_boundary: ChapterBoundary | None = Field(
        default=None,
        description=(
            "Why fewer memories were returned before the target than were asked for. Null "
            "when the full range was available."
        ),
    )
    after_boundary: ChapterBoundary | None = Field(
        default=None,
        description=(
            "Why fewer memories were returned after the target than were asked for. Null "
            "when the full range was available."
        ),
    )
