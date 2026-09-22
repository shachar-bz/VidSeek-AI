"""Turns whatever timing a transcription service supplied into normalized segments.

Two shapes arrive here, and one routine handles both because the difference between them
is only how long each piece is. ElevenLabs hands over individually timed words, which are
far too fine to read: a transcript of one word per line is unusable. A caption track hands
over cues, which are usually too fine as well — an automatic YouTube track scrolls,
emitting a new cue every two or three words, and a hand-written one breaks on the width of
the subtitle box rather than on anything the speaker did. Either way the job is to gather
consecutive pieces into segments of a readable length.

The rule that makes this safe is that a segment boundary is only ever a boundary the
source itself measured. Pieces are merged, never split, so every start and end this module
emits is a timestamp that came from the transcription service. Nothing is interpolated: a
piece with no trustworthy end of its own is never closed at the next piece's start, since
that would claim someone was speaking through whatever pause separates them. A transcript
whose source measured no timing at all, or left a mid-transcript piece with no way to
close it, is rejected rather than given invented timing — see `TimingFidelity` — so the
caller can fall back to timing the same text against the audio instead.

Where a segment ends is decided by, in order: a gap in the speech, the end of a sentence,
and finally a length ceiling, so that a monologue with no pauses and no punctuation still
produces segments a person can read.
"""

import math
import re
from collections.abc import Iterable
from typing import Protocol

from .transcript import NormalizedTranscript, TimingFidelity, TranscriptSegment

# How long a segment should be. Roughly the length of a spoken sentence: short enough to
# seek to usefully, long enough to read as a thought rather than as a fragment.
TARGET_SEGMENT_SECONDS = 8.0

# The ceiling a segment is broken at even mid-sentence, for speech that never pauses.
MAX_SEGMENT_SECONDS = 16.0

# Below this a segment is too short to be worth ending: a pause or a full stop this soon
# after the last boundary is ignored, and the next piece joins the same segment.
MIN_SEGMENT_SECONDS = 1.5

# A silence at least this long is where a speaker actually stopped, which is a better
# place to break than anything the punctuation suggests.
PAUSE_SECONDS = 0.9

# Only ever used for the very last cue of a caption track that gave it no end time, and
# only when the media duration is unknown too. Ordinary speech runs at roughly this rate.
WORDS_PER_SECOND = 2.5

SENTENCE_END_PATTERN = re.compile("[.!?…;:][\"'”’)\\]]?$")


class TimedText(Protocol):
    """What every source's piece of transcript has in common.

    Structural rather than nominal on purpose: ElevenLabs' `TranscriptWord` and
    `backend.core.captions.CaptionSegment` already expose these three names, and neither
    should have to import from here to be normalizable.
    """

    text: str
    start_seconds: float | None
    end_seconds: float | None


class _Piece:
    """One cleaned piece of transcript: non-empty text, with a start and an end."""

    __slots__ = ("text", "start_seconds", "end_seconds")

    def __init__(self, text: str, start_seconds: float, end_seconds: float):
        self.text = text
        self.start_seconds = start_seconds
        self.end_seconds = end_seconds


def _is_usable_time(value) -> bool:
    """A time has to be a real, finite, non-negative number to place anything by."""
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _estimated_reading_seconds(text: str) -> float:
    return max(len(text.split()) / WORDS_PER_SECOND, 1.0)


def _placeable(items: Iterable[TimedText] | None) -> list[tuple[str, float, float | None]]:
    """Keep only the pieces that have both something to say and somewhere to say it.

    Anything without a usable start is dropped: there is nowhere to put it, and guessing
    would be inventing timing.
    """
    placeable = []
    for item in items or ():
        text = " ".join(str(getattr(item, "text", "") or "").split())
        start = getattr(item, "start_seconds", None)
        if not text or not _is_usable_time(start):
            continue
        end = getattr(item, "end_seconds", None)
        placeable.append((text, float(start), float(end) if _is_usable_time(end) else None))
    return placeable


def _clean(items: Iterable[TimedText] | None, media_duration_seconds: float | None) -> list[_Piece]:
    """Put the placeable pieces in order, and refuse to close a gap by guessing.

    A missing or backwards end means the source never measured how long this piece lasted.
    Closing it at the next piece's start would claim someone was speaking for the whole gap
    between them, silence included, so that is not done — a piece like this is worth nothing
    to this module unless it is the last one, with no next piece to wrongly claim speech up
    to. The final piece alone falls back to the media duration, or failing that to how long
    its own text takes to say — the one estimate this module makes, and one that moves a
    single end time by a second or two at the very end of a video. Any other piece missing
    an end fails the whole batch, telling the caller this source cannot be trusted as timed
    so it can fall back to timing the same text against the audio instead.

    Overlaps are trimmed separately, and only once a piece's own end is trusted. Automatic
    caption tracks routinely emit a cue that runs past the start of the one after it, which
    would otherwise produce segments whose ranges overlap and a transcript that no longer
    reads as a sequence.
    """
    placeable = sorted(_placeable(items), key=lambda piece: piece[1])
    pieces = []
    for position, (text, start, end) in enumerate(placeable):
        next_start = placeable[position + 1][1] if position + 1 < len(placeable) else None
        if end is not None and end <= start:
            end = None
        if end is None:
            if next_start is not None:
                return []
            end = (
                media_duration_seconds
                if media_duration_seconds is not None and media_duration_seconds > start
                else start + _estimated_reading_seconds(text)
            )
        elif next_start is not None:
            end = min(end, max(next_start, start))
        pieces.append(_Piece(text, start, max(end, start)))
    return pieces


def _ends_sentence(text: str) -> bool:
    return bool(SENTENCE_END_PATTERN.search(text.rstrip()))


def _starts_new_segment(current: list[_Piece], piece: _Piece) -> bool:
    """Decide whether `piece` opens a new segment instead of joining `current`."""
    span = current[-1].end_seconds - current[0].start_seconds
    if span < MIN_SEGMENT_SECONDS:
        return False
    if piece.start_seconds - current[-1].end_seconds >= PAUSE_SECONDS:
        return True
    if span >= TARGET_SEGMENT_SECONDS and _ends_sentence(current[-1].text):
        return True
    return piece.end_seconds - current[0].start_seconds > MAX_SEGMENT_SECONDS


def _group(pieces: list[_Piece]) -> list[TranscriptSegment]:
    """Gather consecutive pieces into readable segments, splitting none of them."""
    segments: list[TranscriptSegment] = []
    current: list[_Piece] = []

    def close(group: list[_Piece]) -> None:
        segments.append(
            TranscriptSegment(
                index=len(segments),
                start_seconds=group[0].start_seconds,
                end_seconds=group[-1].end_seconds,
                text=" ".join(piece.text for piece in group),
            )
        )

    for piece in pieces:
        if current and _starts_new_segment(current, piece):
            close(current)
            current = []
        current.append(piece)
    if current:
        close(current)
    return segments


def normalize(
    items: Iterable[TimedText] | None,
    *,
    source: str,
    timing_fidelity: TimingFidelity,
    language: str | None = None,
    media_duration_seconds: float | None = None,
) -> NormalizedTranscript | None:
    """Normalize any source's timed pieces, or return None if none can be placed in time.

    None is the signal that this source cannot meet the contract — it produced text with
    no usable timing — and that the caller has to find the timing somewhere else.
    """
    pieces = _clean(items, media_duration_seconds)
    if not pieces:
        return None
    return NormalizedTranscript(
        source=source,
        timing_fidelity=timing_fidelity,
        segments=_group(pieces),
        language=language,
    )


def normalize_caption_cues(
    cues: Iterable[TimedText] | None,
    *,
    source: str,
    language: str | None = None,
    media_duration_seconds: float | None = None,
) -> NormalizedTranscript | None:
    """Normalize a caption track's cues, keeping only boundaries the track measured."""
    return normalize(
        cues,
        source=source,
        timing_fidelity=TimingFidelity.CAPTION,
        language=language,
        media_duration_seconds=media_duration_seconds,
    )


def normalize_words(
    words: Iterable[TimedText] | None,
    *,
    source: str,
    language: str | None = None,
) -> NormalizedTranscript | None:
    """Normalize individually timed words into segments of a readable length."""
    return normalize(
        words,
        source=source,
        timing_fidelity=TimingFidelity.WORD,
        language=language,
    )
