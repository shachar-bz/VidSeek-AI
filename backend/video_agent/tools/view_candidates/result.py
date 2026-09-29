"""What a contact sheet gives back to the agent: a verdict and a description per frame, never the sheet.

Every frame shown was seen, so each one is citable, as an instant: its `start_seconds` and
`end_seconds` are both its own time, the pair the citation check collects
(`video_agent/citations.py`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CandidateFrame(BaseModel):
    """One frame of the contact sheet, what the image model saw there, and whether it shows what was asked."""

    frame: int = Field(description="The frame's number on the sheet, counted from 1, in the order the times were given.")
    time_seconds: float = Field(description="When the frame is shown, in seconds from the beginning of the video.")
    start_seconds: float = Field(description="The same time: a frame looked at can be cited as this instant.")
    end_seconds: float = Field(description="The same time again.")
    timestamp: str = Field(description="The same time written as MM:SS or H:MM:SS.")
    chapter: str | None = Field(default=None, description="The title of the chapter the frame falls in, if any.")
    present: Literal["yes", "no", "unclear"] = Field(
        description="The image model's verdict on whether what the question asks about is in this frame. A signal, not the decision: read it with the description."
    )
    description: str = Field(description="What the image model saw in this frame that bears on the question.")


class ViewedCandidates(BaseModel):
    """The frames looked at on one contact sheet, each with its verdict."""

    frames: list[CandidateFrame] = Field(default_factory=list, description="Every frame looked at, in the order the times were given.")
    note: str | None = Field(
        default=None,
        description="Why fewer frames than asked for were looked at, or none at all, when that happened.",
    )
    budget: str = Field(description="What is left of this answer's visual budget.")
