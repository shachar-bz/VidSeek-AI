"""What one semantic search hit looks like to the agent that asked for it.

A Pydantic model rather than the store's `MemoryMatch` dataclass, because this is the
tool's contract with the model: Pydantic AI turns it into the JSON schema the hit is
serialized against, and the field docstrings below are what the model reads to know that
the times are seconds into the video rather than anything else.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemorySearchHit(BaseModel):
    """One moment of the video whose meaning is close to what was searched for."""

    text: str = Field(description="What was actually said during this moment.")
    summary: str = Field(description="One line describing what this moment is about.")
    chapter_title: str | None = Field(
        default=None,
        description="The title of the chapter this moment belongs to, if it has one.",
    )
    start_seconds: float = Field(description="When this moment starts, in seconds from the beginning of the video.")
    end_seconds: float = Field(description="When this moment ends, in seconds from the beginning of the video.")
