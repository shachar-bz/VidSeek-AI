"""What a video's outline looks like to the agent that asked for it.

Pydantic models rather than the store's dataclasses, for the same reason
`get_chapter_context.result` has its own: this is the tool's contract with the model.
Pydantic AI turns these into the JSON schema the outline is serialized against, and the
field descriptions below are what the model reads to know that the times are seconds into
the video, that the chapters arrive in the order they are watched in, and that a summary
is all it is being given of each one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterOutline(BaseModel):
    """One chapter of the video, named and timed, without any of its contents."""

    chapter_id: str = Field(description="The id of this chapter.")
    chapter_index: int = Field(
        description="This chapter's position in the video, counting from zero.",
    )
    title: str = Field(description="The title given to this chapter.")
    summary: str = Field(description="A short description of what this chapter covers.")
    start_seconds: float = Field(description="When this chapter starts, in seconds from the beginning of the video.")
    end_seconds: float = Field(description="When this chapter ends, in seconds from the beginning of the video.")


class VideoOutline(BaseModel):
    """How the video is organized: its chapters, in the order they are watched in."""

    chapters: list[ChapterOutline] = Field(
        description=(
            "Every chapter of this video, earliest first. Empty when the video has not "
            "been divided into chapters."
        ),
    )
