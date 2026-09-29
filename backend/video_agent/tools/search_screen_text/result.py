"""What an on-screen text search hands the agent: moments where the text was read, each citable.

Unlike a picture match, a moment here was read: OCR found the text on screen through it. So it
carries plain `start_seconds`/`end_seconds`, which the citation check collects
(`video_agent/citations.py`), and the answer may cite it without a look.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScreenTextMoment(BaseModel):
    """One stretch of the video where matching text was on screen, and what was read there."""

    start_seconds: float = Field(
        description="When the text appears on screen, in seconds from the beginning of the video."
    )
    end_seconds: float = Field(description="When it stops being on screen, in seconds.")
    timestamp: str = Field(description="The same stretch written as MM:SS-MM:SS.")
    chapter: str | None = Field(default=None, description="The title of the chapter the moment starts in, if any.")
    found_by: list[str] = Field(
        description=(
            "What matched: `text_characters` (the exact words asked for are written here) or "
            "`text_meaning` (the text means what the query describes)."
        )
    )
    matched_words: list[str] = Field(
        default_factory=list, description="The words asked for that are written here."
    )
    on_screen_text: str | None = Field(
        default=None,
        description=(
            "The text OCR read on one keyframe of this moment; it ends with … when cut, and a "
            "moment running over several keyframes may show more."
        ),
    )
    shot_boundary: str = Field(
        description=(
            "How the shot this moment is in began: `video_start`, `scene_change` (a new shot or "
            "scene) or `text_change` (new text on the same screen, such as the next slide)."
        )
    )


class ScreenTextMoments(BaseModel):
    """What one on-screen text search found, and anything the agent should know about it."""

    moments: list[ScreenTextMoment] = Field(
        default_factory=list,
        description="The exact-word matches first, most words first; then the matches by meaning, closest first.",
    )
    note: str | None = Field(
        default=None, description="Why nothing was found or searched, or that OCR is still reading the video."
    )
