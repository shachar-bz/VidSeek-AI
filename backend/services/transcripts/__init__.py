"""The normalized timestamped transcript every video produces, whatever transcribed it.

This package is the seam between the transcription services and everything that reads a
transcript. Each service keeps its own result type, rich with whatever only it knows —
Scribe's speakers and audio events, a caption track's language tag — and this package
converts all of them into one shape: chronological segments, each with a start, an end,
and the speech between them.

A stage after transcription should import from here and nowhere else. That is what lets
a video transcribed from YouTube captions and one transcribed by ElevenLabs enter the
next stage identically.
"""

from .formatting import SECONDS_PER_HOUR, format_timecode, render_segments
from .normalizer import (
    MAX_SEGMENT_SECONDS,
    TARGET_SEGMENT_SECONDS,
    TimedText,
    normalize,
    normalize_caption_cues,
    normalize_words,
)
from .transcript import NormalizedTranscript, TimingFidelity, TranscriptSegment

__all__ = [
    "MAX_SEGMENT_SECONDS",
    "NormalizedTranscript",
    "SECONDS_PER_HOUR",
    "TARGET_SEGMENT_SECONDS",
    "TimedText",
    "TimingFidelity",
    "TranscriptSegment",
    "format_timecode",
    "normalize",
    "normalize_caption_cues",
    "normalize_words",
    "render_segments",
]
