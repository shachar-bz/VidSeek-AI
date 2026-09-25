"""Transcript selection, parsing, and artifact persistence."""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.core.captions import CaptionSegment, parse_ttml, parse_webvtt_or_srt
from backend.storage import transcript_store
from backend.schemas.browser import CaptionCandidate
from backend.services.forced_alignment import align_text_to_media, is_english_text
from backend.services.transcription.elevenlabs import transcribe_video
from backend.services.transcripts import (
    NormalizedTranscript,
    normalize_caption_cues,
    normalize_words,
)

from .structured import parse_json_captions

MIN_VISIBLE_TRANSCRIPT_CHARACTERS = 80
FORCED_ALIGNMENT_SOURCE = "forced_alignment"

# A BCP 47-shaped tag (`he`, `en-US`, `zh-Hans`), as yt-dlp puts it between a subtitle
# file's name and its extension: `clip.he.vtt`.
SUBTITLE_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptArtifact:
    """One chosen transcript, as its source gave it and as the pipeline passes it on.

    `segments` and `details` are the source's own record, kept because only the source
    knows what it measured. `normalized` is the single shape every later stage reads, and
    it is None for exactly one kind of source: a page transcript, which is text somebody
    published with no timing attached. A None here is what tells the pipeline this
    transcript cannot be handed on as it stands.
    """

    source: str
    text: str
    language: str | None = None
    segments: list[CaptionSegment] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    normalized: NormalizedTranscript | None = None

    @property
    def is_timed(self) -> bool:
        """Whether this transcript carries the timing the next stage requires."""
        return self.normalized is not None


def transcript_from_caption(candidate: CaptionCandidate, media_duration_seconds: float | None = None, *, allow_llm: bool = True) -> TranscriptArtifact | None:
    """Turn a supplied caption body or visible transcript into one artifact."""
    if not candidate.text:
        return None
    if candidate.is_visible_transcript:
        text = " ".join(candidate.text.split())
        if len(text) < MIN_VISIBLE_TRANSCRIPT_CHARACTERS:
            return None
        return TranscriptArtifact(source="page_transcript", text=text, language=candidate.language)

    try:
        segments = parse_json_captions(candidate.text, media_duration_seconds, allow_llm=allow_llm) if candidate.format.lower() == "json" else (
            parse_ttml(candidate.text)
            if candidate.format.lower() in {"ttml", "xml", "dfxp"}
            else parse_webvtt_or_srt(candidate.text)
        )
    except (ElementTree.ParseError, ValueError):
        return None
    if not segments:
        return None
    normalized = normalize_caption_cues(
        segments, source="captions", language=candidate.language, media_duration_seconds=media_duration_seconds
    )
    # A track whose cues carry no times at all — TTML written with no `begin` attributes —
    # or one whose end times cannot be trusted past the last cue, parses into text that
    # cannot be placed in the video. It is no better than a page transcript, so it is
    # offered as one: still worth keeping as a last resort — the pipeline aligns it against
    # the audio instead — but not something it may hand on already timed.
    if normalized is None:
        return TranscriptArtifact(
            source="page_transcript",
            text=" ".join(segment.text for segment in segments),
            language=candidate.language,
        )
    return TranscriptArtifact(
        source="captions",
        text=normalized.text,
        language=candidate.language,
        segments=segments,
        normalized=normalized,
        details={"inferred_end_times": any(c.end_seconds is None for c in segments)},
    )


def choose_supplied_transcript(candidates: list[CaptionCandidate], preferred_language: str | None = None, media_duration_seconds: float | None = None) -> TranscriptArtifact | None:
    """Apply active/manual/automatic/visible ordering to browser candidates."""
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate.is_visible_transcript,
            not candidate.is_active,
            bool(preferred_language) and (candidate.language or "").split("-")[0] != preferred_language.split("-")[0],
            not candidate.is_manual,
        ),
    )
    untimed = None
    unresolved = []
    for candidate in ordered:
        result = transcript_from_caption(candidate, media_duration_seconds, allow_llm=False)
        if result and result.is_timed:
            return result
        untimed = untimed or result
        if result is None and candidate.format.lower() == "json":
            unresolved.append(candidate)
    # At most one schema-inference call per selection, after all known formats were tried.
    if unresolved:
        result = transcript_from_caption(unresolved[0], media_duration_seconds)
        if result and result.is_timed:
            return result
    return untimed


def subtitle_file_language(path: Path) -> str | None:
    """The language yt-dlp named a subtitle file after, or None if its name carries none."""
    suffixes = path.suffixes
    if len(suffixes) < 2:
        return None
    tag = suffixes[-2].lstrip(".")
    return tag if SUBTITLE_LANGUAGE_TAG.match(tag) else None


def transcript_from_subtitle_files(paths: list[Path]) -> TranscriptArtifact | None:
    """Use the first valid subtitle file produced by yt-dlp."""
    for path in sorted(paths, key=lambda item: item.suffix.lower() not in {".vtt", ".srt"}):
        candidate = CaptionCandidate(
            text=path.read_text(encoding="utf-8", errors="replace"),
            format=path.suffix.lstrip("."),
            language=subtitle_file_language(path),
            is_manual=True,
        )
        result = transcript_from_caption(candidate)
        if result:
            return result
    return None


def transcribe_with_elevenlabs(video_path: Path) -> TranscriptArtifact:
    """Use the existing Scribe integration and preserve its full timed result.

    Scribe's own words, speakers and audio events stay in `details`; `normalized` holds
    those same words gathered into readable segments. Audio events are left out of the
    segments deliberately — `[music]` is not speech, and a search index that treats it as
    speech reports a song as something somebody said.
    """
    result = transcribe_video(str(video_path))
    return TranscriptArtifact(
        source="elevenlabs",
        text=result.speech_text,
        language=result.language_code,
        details=asdict(result),
        normalized=normalize_words(
            result.words, source="elevenlabs", language=result.language_code
        ),
    )


def align_supplied_transcript(
    video_path: Path, supplied: TranscriptArtifact
) -> TranscriptArtifact | None:
    """Time a transcript already in hand against the video, instead of retranscribing it.

    Forced alignment fits the exact words already supplied onto the video's audio, which
    is cheaper than throwing that text away and transcribing from scratch, and keeps
    whatever the original text got right that a fresh transcription might not. It
    understands only English, so a transcript in any other language is left for the
    caller to send to full transcription instead — and so is any failure calling it, since
    that same fallback is still there to catch it.
    """
    if not is_english_text(supplied.text):
        return None
    try:
        result = align_text_to_media(str(video_path), supplied.text)
    except Exception:
        logger.warning(
            "Forced alignment failed for %s; falling back to transcription", video_path
        )
        return None
    normalized = normalize_words(result.words, source=FORCED_ALIGNMENT_SOURCE, language="en")
    if normalized is None:
        return None
    return TranscriptArtifact(
        source=FORCED_ALIGNMENT_SOURCE,
        text=supplied.text,
        language="en",
        details=asdict(result),
        normalized=normalized,
    )


def persist_transcript(
    video_path: Path, artifact: TranscriptArtifact
) -> tuple[Path, Path]:
    """Write the transcript beside the video, and store it for the next stage.

    Three things are written, and they are for three different readers. The `.txt` is the
    normalized `[MM:SS-MM:SS] text` transcript, which is what a person opens and what the
    next stage consumes. The `.json` beside it adds the machine-readable segments and the
    source's own untouched record, so a change to the normalizer can be replayed against
    what the service actually returned. The store — keyed by the video's own id rather
    than by a path — is where the pipeline looks the transcript up later, and is the part
    a database will take over.

    An untimed transcript is still written out, because text is better than nothing and
    the caller may have nowhere else to get it, but it is deliberately not stored: the
    store holds normalized transcripts, and a stage reading one must never have to ask
    whether the timings in it are real.
    """
    text_path = video_path.with_suffix(".transcript.txt")
    json_path = video_path.with_suffix(".transcript.json")
    normalized = artifact.normalized
    text_path.write_text(
        normalized.formatted_text if normalized else artifact.text, encoding="utf-8"
    )
    payload = {
        "source": artifact.source,
        "language": artifact.language,
        "text": artifact.text,
        "video_path": str(video_path),
        "normalized": normalized.to_payload() if normalized else None,
        "source_segments": [asdict(segment) for segment in artifact.segments],
        "details": artifact.details,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if normalized:
        transcript_store.save(video_path.stem, normalized)
    return text_path, json_path
