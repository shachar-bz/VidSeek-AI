"""What a semantic search hands the agent: the moments found, and a note when they are weak.

Pydantic models rather than the store's `ScoredMemory` dataclass, because this is the tool's
contract with the model: Pydantic AI serializes the result against them. The field descriptions
below are code documentation only -- the return schema is not sent to the model -- so anything
the model must know about the result is said in the tool's docstring instead.

Every moment keeps `start_seconds`/`end_seconds`, weak ones included, and that is on purpose:
the citation check collects every such pair in a tool result (`video_agent/citations.py`). A
weak moment is still speech actually retrieved from the video, its text what was said then, so
citing it is citing something the agent has read -- unlike a weak picture frame, which nobody
has seen (`search_visual_moments/result.py`). No similarity or z-score is carried: the agent
judges a moment by what it says, and `weak` is all it needs to know about how it was found.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemorySearchHit(BaseModel):
    """One moment of the video whose meaning is close to what was searched for."""

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
    weak: bool = Field(
        default=False,
        description="True when nothing stood out and this is only one of the closest moments: probably not what was asked for.",
    )


class MemorySearchResult(BaseModel):
    """What one semantic search found, closest first, and anything the agent should know about it."""

    moments: list[MemorySearchHit] = Field(default_factory=list, description="The moments found, closest first.")
    note: str | None = Field(
        default=None, description="That nothing stood out and the moments are weak, or that there was nothing to search."
    )
