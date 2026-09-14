"""The transcript data model of the YouTube download module.

A transcript here arrives from one of two places, and they do not have the same shape.
YouTube's own caption track comes as timed lines of a phrase or two each; ElevenLabs'
Scribe comes as individually timed words. Neither converts into the other without
inventing timings that were never measured, so both are kept exactly as they arrived and
`source` says which one is in hand.

`normalized` is what every consumer outside this module should read: the same timed
segments whichever of the two produced them, so that nothing downstream has to know which
did. `text` is the transcript as one unstamped string, kept for the places that only want
the words.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from backend.services.transcripts import NormalizedTranscript

# Imported for the annotation alone. A hard import would pull the ElevenLabs SDK in every
# time this module is touched, including for the caption path that never transcribes
# anything, and would break this module outright if the elevenlabs service is ever
# dropped from the project.
if TYPE_CHECKING:
    from backend.services.transcription.elevenlabs import TranscriptionResult

CAPTIONS_SOURCE = "youtube_captions"
ELEVENLABS_SOURCE = "elevenlabs"

TranscriptSource = Literal["youtube_captions", "elevenlabs"]


@dataclass(frozen=True)
class CaptionSegment:
    """One timed line of a YouTube caption track."""

    text: str
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class YouTubeTranscript:
    """A video's speech as text, plus whatever timing came with it.

    Exactly one of `segments` and `elevenlabs_result` is ever filled, and `source` says
    which to read: caption segments for `youtube_captions`, the full Scribe result — words,
    speakers and audio events — for `elevenlabs`.
    """

    source: TranscriptSource
    text: str
    segments: list[CaptionSegment] = field(default_factory=list)
    elevenlabs_result: "TranscriptionResult | None" = None
    normalized: NormalizedTranscript | None = None

    @property
    def is_from_captions(self) -> bool:
        return self.source == CAPTIONS_SOURCE

    @property
    def is_timed(self) -> bool:
        """Whether this transcript carries the timing the next stage requires."""
        return self.normalized is not None

    @property
    def timestamped_text(self) -> str:
        """The transcript as it is written out: `[MM:SS-MM:SS] text` lines when timed.

        A transcript with no timing falls back to the plain words. That only happens when
        a source returned text it measured nothing about, which is worth keeping but is
        not what the next stage is promised.
        """
        return self.normalized.formatted_text if self.normalized else self.text
