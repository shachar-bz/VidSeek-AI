"""What a close view hands back as its return value: which frames were shown, and nothing about what they show.

The frames themselves reach the agent beside this, as images (`tool.py`). Each one was seen, so
it is citable as an instant: its `start_seconds` and `end_seconds` are both its own time, the
pair the citation check collects (`video_agent/citations.py`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CloseupFrame(BaseModel):
    """One frame shown to the agent large."""

    frame: int = Field(description="The frame's number: the image labelled 'Frame N' after this result.")
    time_seconds: float = Field(description="When the frame is shown, in seconds from the beginning of the video.")
    start_seconds: float = Field(description="The same time: a frame looked at can be cited as this instant.")
    end_seconds: float = Field(description="The same time again.")
    timestamp: str = Field(description="The same time written as MM:SS or H:MM:SS.")
    chapter: str | None = Field(default=None, description="The title of the chapter the frame falls in, if any.")


class CloseupFrames(BaseModel):
    """The frames shown in one close view."""

    frames: list[CloseupFrame] = Field(default_factory=list, description="Every frame shown, in the order asked for.")
    note: str | None = Field(
        default=None,
        description="Why fewer frames than asked for were shown, or none at all, when that happened.",
    )
    budget: str = Field(description="What is left of this answer's visual budget.")
