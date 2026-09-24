"""What a visual investigation hands back to the main agent, and the check its findings pass.

Text only: the main agent never sees a frame. Every finding carries plain `start_seconds` and
`end_seconds`, which is all the main agent's citation check needs -- it collects every such
pair in a tool result (`video_agent/citations.py`), so a finding is a moment it may cite.

That makes a finding's times a promise, so they are checked here before they leave: the whole
finding must lie inside what this investigation's own tools returned -- a frame it looked at, a
scene of a sequence, a keyframe text's stretch, a transcript piece, a moment found by on-screen
text. Spans that overlap or touch join into one stretch, so a finding may run across two
adjacent transcript pieces, but not from one returned moment to another far away with nothing
between them. The main agent holds its own citations to the same kind of rule, written again
rather than imported, because `visual_agent` never imports `video_agent`.
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
    """The findings that do not lie inside one stretch of the spans the investigation's tools returned."""
    stretches = covered_stretches(spans)
    return [
        finding
        for finding in findings
        if finding.end_seconds < finding.start_seconds
        or not any(
            start - SLACK_SECONDS <= finding.start_seconds and finding.end_seconds <= end + SLACK_SECONDS
            for start, end in stretches
        )
    ]


def covered_stretches(spans: Sequence[TimeSpan]) -> list[TimeSpan]:
    """The returned spans joined into stretches, wherever they overlap or come within the slack of each other."""
    stretches: list[TimeSpan] = []
    for start, end in sorted(spans):
        if stretches and start <= stretches[-1][1] + SLACK_SECONDS:
            stretches[-1] = (stretches[-1][0], max(stretches[-1][1], end))
        else:
            stretches.append((start, end))
    return stretches
