"""What a chapter looks like to the agent that asked for it.

Pydantic models rather than the store's dataclasses, for the same reason
`memories_semantic_search.result` has its own: this is the tool's contract with the model.
Pydantic AI serializes the chapter through these, but the model is not sent their schema: it
sees field names and values only. So what it must know to read the result, that a moment's
summary is all it is being given, is said in the tool's docstring, and the field descriptions
below document the code.
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
