"""What a search of the video's speech hands the agent: the closest moments, and a note when there was nothing to search.

Pydantic models rather than the store's `ScoredMemory` dataclass, because this is the tool's
contract with the model: Pydantic AI serializes the result against them. The field descriptions
below are code documentation only -- the return schema is not sent to the model -- so anything
the model must know about the result is said in the tool's docstring instead.

Every moment keeps `start_seconds`/`end_seconds`, and that is on purpose: the citation check
collects every such pair in a tool result (`video_agent/citations.py`). A moment is speech
actually retrieved from the video, its text what was said then, so citing it is citing
something the agent has read -- even when it turns out to be off-topic. No similarity or rank
score is carried: the agent judges a moment by what it says.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemorySearchHit(BaseModel):
    """One moment of the video among the closest to what was searched for."""

    memory_id: str = Field(description="The id of the memory this moment is stored as.")
    chapter_id: str | None = Field(
        default=None,
        description="The id of the chapter this moment belongs to, if it has one.",
    )
    chapter_title: str | None = Field(
        default=None,
        description="The title of the chapter this moment belongs to, if it has one.",
    )
    summary: str = Field(description="One line describing what this moment is about.")
    text: str = Field(description="What was actually said during this moment.")
    start_seconds: float = Field(description="When this moment starts, in seconds from the beginning of the video.")
    end_seconds: float = Field(description="When this moment ends, in seconds from the beginning of the video.")


class MemorySearchResult(BaseModel):
    """What one search of the video's speech found, closest first, and anything the agent should know about it."""

    moments: list[MemorySearchHit] = Field(default_factory=list, description="The moments found, closest first.")
    note: str | None = Field(default=None, description="That there was nothing to search, when the video has no moments.")
