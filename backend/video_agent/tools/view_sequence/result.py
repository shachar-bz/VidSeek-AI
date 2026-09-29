"""What looking at a sequence gives back to the agent: the image model's words and the scenes, never the grid.

Only what the frames showed may be cited: from the first frame of a scene to its last. So each
scene's `start_seconds`/`end_seconds` are those frames' times, and nothing else here carries the
pair -- the citation check collects every such pair in a tool result (`video_agent/citations.py`).
A scene's own bounds, from the index, and the window's first and last frame (which may lie in
different scenes) go by other names.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SequenceFrame(BaseModel):
    """One cell of the grid, which scene it is in, and what the image model saw there."""

    frame: int = Field(
        description="The cell's number in the grid, counted from 1: the number the image model's answer names it by."
    )
    time_seconds: float = Field(description="When the frame is shown, in seconds from the beginning of the video.")
    timestamp: str = Field(description="The same time written as MM:SS or H:MM:SS.")
    scene: int | None = Field(
        default=None,
        description="Which scene of this window the frame is in, counted from 1; None when the scenes are not known.",
    )
    chapter: str | None = Field(default=None, description="The title of the chapter the frame falls in, if any.")
    observation: str = Field(description="What the image model saw in this frame that bears on the question.")


class SequenceScene(BaseModel):
    """One scene the frames come from, and the stretch of it they showed."""

    scene: int | None = Field(
        default=None,
        description="The scene's number within this window, counted from 1; None when the scenes are not known and this is the whole window.",
    )
    start_seconds: float = Field(description="The time of the first frame looked at in this scene.")
    end_seconds: float = Field(description="The time of the last frame looked at in this scene.")
    frames: str = Field(description="The same stretch written as MM:SS-MM:SS.")
    scene_start_seconds: float | None = Field(
        default=None,
        description="Where the whole scene starts, from the index. Only the frames' own times were looked at.",
    )
    scene_end_seconds: float | None = Field(default=None, description="Where the whole scene ends, from the index.")


class ViewedSequence(BaseModel):
    """The frames looked at across one window, the scenes they come from, and what happens across them."""

    first_frame_seconds: float | None = Field(default=None, description="The time of the first frame looked at.")
    last_frame_seconds: float | None = Field(default=None, description="The time of the last frame looked at.")
    frames: list[SequenceFrame] = Field(default_factory=list, description="Every frame of the grid, in time order.")
    scenes: list[SequenceScene] = Field(
        default_factory=list,
        description="The scenes the frames come from, in order; one entry for the whole window when the scenes are not known.",
    )
    answer: str | None = Field(
        default=None, description="The image model's answer: what happens across the frames, and when."
    )
    note: str | None = Field(
        default=None,
        description="What to know about this sequence: a cut inside the window, a window chosen for you, or why nothing was looked at.",
    )
    budget: str = Field(description="What is left of this answer's visual budget.")
