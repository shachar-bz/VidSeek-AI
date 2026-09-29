"""What a picture search hands the agent: frames that resemble a description, and nothing citable.

A frame here resembles the query; it is not known to show it. So no field is named
`start_seconds`/`end_seconds`: the citation check collects every such pair in a tool result
(`video_agent/citations.py`), and a frame only the embeddings have seen must not become
something the answer may cite. It becomes citable once a look tool has shown it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PictureMatch(BaseModel):
    """One frame whose picture resembles the query, and the shot it is in."""

    frame_seconds: float = Field(
        description="When the frame is, in seconds from the beginning of the video: the best-matching frame of its shot."
    )
    timestamp: str = Field(description="The same time written as MM:SS.")
    shot_start_seconds: float = Field(description="Where the shot the frame is in starts, in seconds.")
    shot_end_seconds: float = Field(description="Where that shot ends, in seconds.")
    chapter: str | None = Field(default=None, description="The title of the chapter the frame is in, if any.")
    score: float = Field(
        description="How far the frame stood out from the rest of this video, in standard deviations; higher is a stronger match."
    )
    weak: bool = Field(
        default=False,
        description="True when nothing stood out and this is only one of the closest frames: probably not what was asked for.",
    )


class PictureMatches(BaseModel):
    """What one picture search found, best first, and anything the agent should know about it."""

    frames: list[PictureMatch] = Field(default_factory=list, description="The frames found, best first.")
    note: str | None = Field(
        default=None, description="Why nothing was searched, or that nothing stood out and the frames are weak."
    )
