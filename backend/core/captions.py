"""Shared caption parsing primitives used by every download pipeline.

`CaptionSegment`, timestamp parsing, cue-text cleaning and the generic WebVTT/SRT/TTML
parsers live here so a fix to any of them reaches every caller. Pipeline-specific caption
handling — YouTube's scrolling-caption dedup and per-word timestamp extraction, in
particular — stays where it is, since it is not shared logic and does not belong here.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

# A WebVTT or SRT timestamp: hours optional, comma or dot before the milliseconds.
_TIMESTAMP = r"\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}"

# One cue: its timing line, then its text up to a blank line, the next cue's timing line
# (with or without an SRT identifier above it), or the end of the file.
CUE_PATTERN = re.compile(
    rf"(?P<start>{_TIMESTAMP})\s+-->\s+(?P<end>{_TIMESTAMP})[^\n]*\n"
    rf"(?P<text>.*?)(?=\n\s*\n|\n(?:\d+\n)?{_TIMESTAMP}\s+-->|\Z)",
    re.DOTALL,
)


@dataclass(frozen=True)
class CaptionSegment:
    """One timed caption cue."""

    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None


def parse_timestamp_seconds(value: str) -> float:
    """Seconds from a WebVTT/SRT timestamp, tolerant of both dialects.

    SRT uses a comma decimal separator where WebVTT uses a dot, and a timestamp may omit
    the hours (`MM:SS.mmm`) or, rarer still, the minutes as well.
    """
    parts = value.strip().replace(",", ".").split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) > 1 else 0
    hours = int(parts[-3]) if len(parts) > 2 else 0
    return hours * 3600 + minutes * 60 + seconds


def clean_caption_text(value: str) -> str:
    """Strip styling tags and decode entities, leaving only what was said."""
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).replace("‎", "").replace("‏", "").strip()


def parse_webvtt_or_srt(content: str) -> list[CaptionSegment]:
    """Parse ordinary WebVTT or SRT cues without retaining formatting tags.

    A cue's text ends at a blank line, or at the next cue's timing line when the file leaves
    the blank line out, as some sites' tracks do. Without the second stop the next cue is
    swallowed whole, its timing line read as speech and its words timed as this cue's.
    A number on the line just before that timing line is the next cue's SRT identifier.
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    segments = []
    for match in CUE_PATTERN.finditer(normalized):
        cue_text = clean_caption_text(" ".join(match.group("text").splitlines()))
        if cue_text:
            segments.append(
                CaptionSegment(
                    text=cue_text,
                    start_seconds=parse_timestamp_seconds(match.group("start")),
                    end_seconds=parse_timestamp_seconds(match.group("end")),
                )
            )
    return segments


def parse_ttml(content: str) -> list[CaptionSegment]:
    """Parse TTML paragraph cues and ignore presentation-only XML."""
    root = ElementTree.fromstring(content)
    segments = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "p":
            continue
        text = clean_caption_text(" ".join("".join(element.itertext()).split()))
        if not text:
            continue
        begin = element.attrib.get("begin")
        end = element.attrib.get("end")
        segments.append(
            CaptionSegment(
                text=text,
                start_seconds=parse_timestamp_seconds(begin) if begin and ":" in begin else None,
                end_seconds=parse_timestamp_seconds(end) if end and ":" in end else None,
            )
        )
    return segments
