"""What was said in a window of the video, as the sub-agent reads it."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptPiece(BaseModel):
    """One timed piece of the transcript."""

    start_seconds: float = Field(description="When this piece starts, in seconds from the beginning of the video.")
    end_seconds: float = Field(description="When this piece ends, in seconds from the beginning of the video.")
    text: str = Field(description="What was said.")


class TranscriptWindow(BaseModel):
    """Everything said in a window, in order."""

    start_seconds: float = Field(description="The start of the window that was read, in seconds.")
    end_seconds: float = Field(description="The end of the window that was read, in seconds.")
    chapter: str | None = Field(default=None, description="The title of the chapter the window starts in, if any.")
    pieces: list[TranscriptPiece] = Field(
        default_factory=list, description="What was said, in order. Empty when nothing was said."
    )
    note: str | None = Field(default=None, description="How the window was narrowed or cut, if it was.")
    budget: str = Field(description="What is left of the investigation's budget.")
