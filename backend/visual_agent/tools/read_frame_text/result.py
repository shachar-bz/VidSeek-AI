"""What reading the on-screen text at some times gives back to the sub-agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Where a frame's text came from: read when the video was indexed, read just now, or not read
# at all because OCR is not available.
STORED = "stored"
READ_NOW = "read_now"
UNREAD = "unread"


class FrameText(BaseModel):
    """The text shown on screen at one of the times asked for."""

    time_seconds: float = Field(description="The time asked for, in seconds from the beginning of the video.")
    timestamp: str = Field(description="The same time written as MM:SS or H:MM:SS.")
    text: str | None = Field(
        description="The text on screen, one block per line; None when there is none, or it was not read."
    )
    source: Literal["stored", "read_now", "unread"] = Field(
        description=(
            "`stored`: read when the video was indexed, from a keyframe whose text covers this "
            "time. `read_now`: this very frame was read for this call. `unread`: not read; see note."
        )
    )
    start_seconds: float = Field(
        description="The start of the stretch of video this text is known to be shown for, in seconds."
    )
    end_seconds: float = Field(
        description="The end of that stretch, in seconds; the same as start_seconds for a single frame."
    )
    chapter: str | None = Field(default=None, description="The title of the chapter this time falls in, if any.")
    note: str | None = Field(default=None, description="Why the text was not read, when it was not.")


class FrameTexts(BaseModel):
    """The on-screen text at each time asked for, in the same order."""

    texts: list[FrameText] = Field(default_factory=list)
    note: str | None = Field(default=None, description="Why fewer times than asked for were read, or none at all, when that happened.")
    budget: str = Field(description="What is left of the investigation's budget.")
