"""What looking at frames gives back to the sub-agent: the image model's words, never the frames."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ViewedFrame(BaseModel):
    """One frame the image model looked at, and what it saw there."""

    time_seconds: float = Field(description="When the frame is shown, in seconds from the beginning of the video.")
    timestamp: str = Field(description="The same time written as MM:SS or H:MM:SS.")
    chapter: str | None = Field(default=None, description="The title of the chapter the frame falls in, if any.")
    observation: str = Field(description="What the image model saw in this frame that bears on the question.")


class ViewedFrames(BaseModel):
    """The frames looked at in one call, and the image model's answer across them."""

    frames: list[ViewedFrame] = Field(default_factory=list, description="Every frame looked at, in the order asked for.")
    answer: str | None = Field(
        default=None, description="The image model's answer to the question across all the frames."
    )
    note: str | None = Field(
        default=None,
        description="Why fewer frames than asked for were looked at, or none at all, when that happened.",
    )
    budget: str = Field(description="What is left of the investigation's budget.")
