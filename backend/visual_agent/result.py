"""What a visual investigation hands back to the main agent, and the check its findings pass.

Text only: the main agent never sees a frame. Every finding carries plain `start_seconds` and
`end_seconds`, which is all the main agent's citation check needs -- it collects every such
pair in a tool result (`video_agent/citations.py`), so a finding is a moment it may cite.

That makes a finding's times a promise, so they are checked here before they leave: each end of
a finding must fall inside a span one of this investigation's own tools returned -- a frame it
looked at, a keyframe text's stretch, a transcript piece. The same rule the main agent holds
its own citations to, written again rather than imported, because `visual_agent` never imports
`video_agent`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

TimeSpan = tuple[float, float]

# A finding's end is accepted this close to a returned span. Tool results carry float seconds
# and the model writes them back rounded, so 734.6 may honestly come back as 734 or 735.
SLACK_SECONDS = 1.0

Evidence = Literal["ocr", "image", "transcript"]


class VisualFinding(BaseModel):
    """One thing the investigation saw, where it saw it, and what showed it."""

    start_seconds: float = Field(description="Where the finding starts, in seconds from the beginning of the video.")
    end_seconds: float = Field(
        description=(
            "Where the finding ends, in seconds from the beginning of the video; the same as "
            "start_seconds for something seen in a single frame."
        )
    )
    chapter: str | None = Field(
        default=None, description="The title of the chapter this moment falls in, if a tool gave one."
    )
    observation: str = Field(description="What was seen, read or heard at this moment, in one or two sentences.")
    evidence: Evidence = Field(
        description=(
            "What the observation rests on: `image` for a frame that was looked at, `ocr` for "
            "on-screen text that was read, `transcript` for what was said."
        )
    )


class VisualInvestigation(BaseModel):
    """The answer to one visual question, and the moments it rests on."""

    answer: str = Field(
        description=(
            "The answer to the question, in plain words. Says so when the answer was not found "
            "or is uncertain."
        )
    )
    findings: list[VisualFinding] = Field(
        default_factory=list,
        description="The moments the answer rests on, earliest first. Empty when nothing was found.",
    )


def unsupported_findings(
    findings: Sequence[VisualFinding], spans: Sequence[TimeSpan]
) -> list[VisualFinding]:
    """The findings whose start or end falls in no span the investigation's tools returned."""
    return [
        finding
        for finding in findings
        if finding.end_seconds < finding.start_seconds
        or not (_returned(finding.start_seconds, spans) and _returned(finding.end_seconds, spans))
    ]


def _returned(second: float, spans: Sequence[TimeSpan]) -> bool:
    return any(start - SLACK_SECONDS <= second <= end + SLACK_SECONDS for start, end in spans)
