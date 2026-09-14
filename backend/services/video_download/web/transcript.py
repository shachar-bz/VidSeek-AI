"""Transcript selection, parsing, Firecrawl extraction, and artifact persistence."""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

from backend.core import config
from backend.schemas.browser import CaptionCandidate
from backend.services.transcription.elevenlabs import transcribe_video

FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v2/scrape"
FIRECRAWL_API_KEY_NAME = "FIRECRAWL_API_KEY"
MIN_VISIBLE_TRANSCRIPT_CHARACTERS = 80


@dataclass(frozen=True)
class CaptionSegment:
    """One timed caption cue."""

    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None


@dataclass(frozen=True)
class TranscriptArtifact:
    """One chosen transcript and the fidelity supplied by its source."""

    source: str
    text: str
    language: str | None = None
    segments: list[CaptionSegment] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def _timestamp_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        parts.insert(0, "0")
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _clean_caption_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).replace("\u200e", "").replace("\u200f", "").strip()


def parse_webvtt_or_srt(content: str) -> list[CaptionSegment]:
    """Parse ordinary WebVTT or SRT cues without retaining formatting tags."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    timing = re.compile(
        r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+"
        r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})[^\n]*\n"
        r"(?P<text>.*?)(?=\n\s*\n|\Z)",
        re.DOTALL,
    )
    segments = []
    for match in timing.finditer(normalized):
        cue_text = _clean_caption_text(" ".join(match.group("text").splitlines()))
        if cue_text:
            segments.append(
                CaptionSegment(
                    text=cue_text,
                    start_seconds=_timestamp_seconds(match.group("start")),
                    end_seconds=_timestamp_seconds(match.group("end")),
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
        text = _clean_caption_text(" ".join("".join(element.itertext()).split()))
        if not text:
            continue
        begin = element.attrib.get("begin")
        end = element.attrib.get("end")
        segments.append(
            CaptionSegment(
                text=text,
                start_seconds=_timestamp_seconds(begin) if begin and ":" in begin else None,
                end_seconds=_timestamp_seconds(end) if end and ":" in end else None,
            )
        )
    return segments


def transcript_from_caption(candidate: CaptionCandidate) -> TranscriptArtifact | None:
    """Turn a supplied caption body or visible transcript into one artifact."""
    if not candidate.text:
        return None
    if candidate.is_visible_transcript:
        text = " ".join(candidate.text.split())
        if len(text) < MIN_VISIBLE_TRANSCRIPT_CHARACTERS:
            return None
        return TranscriptArtifact(source="page_transcript", text=text, language=candidate.language)

    try:
        segments = (
            parse_ttml(candidate.text)
            if candidate.format.lower() in {"ttml", "xml"}
            else parse_webvtt_or_srt(candidate.text)
        )
    except (ElementTree.ParseError, ValueError):
        return None
    if not segments:
        return None
    return TranscriptArtifact(
        source="captions",
        text=" ".join(segment.text for segment in segments),
        language=candidate.language,
        segments=segments,
    )


def choose_supplied_transcript(candidates: list[CaptionCandidate]) -> TranscriptArtifact | None:
    """Apply active/manual/automatic/visible ordering to browser candidates."""
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate.is_visible_transcript,
            not candidate.is_active,
            not candidate.is_manual,
        ),
    )
    for candidate in ordered:
        result = transcript_from_caption(candidate)
        if result:
            return result
    return None


def transcript_from_subtitle_files(paths: list[Path]) -> TranscriptArtifact | None:
    """Use the first valid subtitle file produced by yt-dlp."""
    for path in sorted(paths, key=lambda item: item.suffix.lower() not in {".vtt", ".srt"}):
        candidate = CaptionCandidate(
            text=path.read_text(encoding="utf-8", errors="replace"),
            format=path.suffix.lstrip("."),
            is_manual=True,
        )
        result = transcript_from_caption(candidate)
        if result:
            return result
    return None


def _firecrawl_api_key() -> str | None:
    return config.get(FIRECRAWL_API_KEY_NAME)


def _comparable_text(value: str) -> str:
    value = re.sub(r"[*_`#>\[\]()]", " ", value)
    return " ".join(value.split()).casefold()


def _without_credentials_in_query(page_url: str) -> str:
    """Drop the query and fragment, which carry this session's signed parameters."""
    parsed = urlsplit(page_url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def scrape_public_page_transcript(page_url: str, timeout_seconds: float = 65.0) -> str | None:
    """Extract a verbatim public transcript without sending browser credentials."""
    api_key = _firecrawl_api_key()
    if not api_key:
        return None
    public_url = _without_credentials_in_query(page_url)
    schema = {
        "type": "object",
        "properties": {
            "transcript_found": {"type": "boolean"},
            "transcript_text": {"type": "string"},
        },
        "required": ["transcript_found", "transcript_text"],
    }
    response = requests.post(
        FIRECRAWL_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "url": public_url,
            "formats": [
                "markdown",
                {
                    "type": "json",
                    "schema": schema,
                    "prompt": (
                        "Return only the complete verbatim spoken transcript or captions "
                        "published on this page. Do not summarize or invent missing text."
                    ),
                },
            ],
            "onlyMainContent": True,
            "storeInCache": False,
            "timeout": 60_000,
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    extracted = data.get("json") or {}
    transcript_text = " ".join(str(extracted.get("transcript_text") or "").split())
    markdown = str(data.get("markdown") or "")
    if not extracted.get("transcript_found") or not transcript_text:
        return None
    if _comparable_text(transcript_text) not in _comparable_text(markdown):
        return None
    return transcript_text


def transcribe_with_elevenlabs(video_path: Path) -> TranscriptArtifact:
    """Use the existing Scribe integration and preserve its full timed result."""
    result = transcribe_video(str(video_path))
    return TranscriptArtifact(
        source="elevenlabs",
        text=result.speech_text,
        language=result.language_code,
        details=asdict(result),
    )


def persist_transcript(
    video_path: Path, artifact: TranscriptArtifact
) -> tuple[Path, Path]:
    """Write human-readable and structured transcript artifacts beside the video."""
    text_path = video_path.with_suffix(".transcript.txt")
    json_path = video_path.with_suffix(".transcript.json")
    text_path.write_text(artifact.text, encoding="utf-8")
    payload = {
        "source": artifact.source,
        "language": artifact.language,
        "text": artifact.text,
        "segments": [asdict(segment) for segment in artifact.segments],
        "details": artifact.details,
        "video_path": str(video_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return text_path, json_path

