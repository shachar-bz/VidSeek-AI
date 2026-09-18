"""What a chapter looks like to the agent that asked for it.

Pydantic models rather than the store's dataclasses, for the same reason
`memories_semantic_search.result` has its own: this is the tool's contract with the model.
Pydantic AI turns these into the JSON schema the chapter is serialized against, and the
field descriptions below are what the model reads to know that the times are seconds into
the video and that a memory's summary is all it is being given.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterMemory(BaseModel):
    """One moment of the video, as it appears inside the chapter it belongs to."""

    memory_id: str = Field(description="The id of the memory this moment is stored as.")
    summary: str = Field(description="One line describing what this moment is about.")
    start_seconds: float = Field(description="When this moment starts, in seconds from the beginning of the video.")
    end_seconds: float = Field(description="When this moment ends, in seconds from the beginning of the video.")


class ChapterContext(BaseModel):
    """One whole chapter of the video: what it covers, when, and every moment in it."""

    chapter_id: str = Field(description="The id of this chapter.")
    chapter_index: int = Field(
        description="This chapter's position in the video, counting from zero.",
    )
    title: str = Field(description="The title given to this chapter.")
    summary: str = Field(description="A short description of what this chapter covers.")
    start_seconds: float = Field(description="When this chapter starts, in seconds from the beginning of the video.")
    end_seconds: float = Field(description="When this chapter ends, in seconds from the beginning of the video.")
    memories: list[ChapterMemory] = Field(
        description=(
            "Every moment in this chapter, earliest first. Empty when the chapter has no "
            "moments grouped into it."
        ),
    )
