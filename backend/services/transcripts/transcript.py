"""The one transcript shape every video produces, whatever transcribed it.

Each transcription service in this project hands back something different: ElevenLabs
times individual words, YouTube's caption track times lines of a phrase or two, and the
OpenAI pipeline times whole chunks until a forced-alignment pass narrows them. A stage
reading one of those directly would have to branch on which service ran, and would break
the day a fourth is added.

`NormalizedTranscript` is what they are all converted into before anything else sees
them: an ordered list of segments, each with a start, an end, and the speech heard
between the two. `timing_fidelity` records how finely the original timing was measured,
for anything that wants to weigh a boundary's precision. It is metadata only — the
segments read the same either way, and nothing downstream has to look at it.
"""

from dataclasses import dataclass, field
from enum import Enum

from .formatting import render_segments


class TimingFidelity(str, Enum):
    """How finely the source measured the timing these segments were built from.

    There is deliberately no value for "estimated". Every boundary in a normalized
    transcript is a timestamp some service actually measured, and a transcript with no
    measured timing is not normalized at all — it is rejected, so that no stage further
    down can mistake an invented number for a real one.
    """

    # Every word was timed individually, so a segment boundary can fall between any two
    # words: ElevenLabs' Scribe, or a forced-alignment pass.
    WORD = "word"

    # Timing came in cue-sized pieces, so boundaries land only where a cue began or
    # ended: a WebVTT, SRT or TTML caption track.
    CAPTION = "caption"


@dataclass(frozen=True)
class TranscriptSegment:
    """One stretch of speech, and the time range it was spoken in."""

    index: int
    start_seconds: float
    end_seconds: float
    text: str

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class NormalizedTranscript:
    """A whole video's speech as timed segments, in chronological order.

    `source` names the service the text came from, for logs and for the extension's
    status line. It is not a switch: the segments mean the same thing whichever value it
    holds, and a consumer that branches on it has misread this type.
    """

    source: str
    timing_fidelity: TimingFidelity
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str | None = None

    @property
    def text(self) -> str:
        """The speech alone, with no timestamps, as one line."""
        return " ".join(segment.text for segment in self.segments)

    @property
    def formatted_text(self) -> str:
        """The transcript as `[MM:SS-MM:SS] text` lines — the format every stage reads."""
        return render_segments(self.segments)

    @property
    def duration_seconds(self) -> float:
        """How far into the video the last spoken segment ends."""
        return self.segments[-1].end_seconds if self.segments else 0.0

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    def to_payload(self) -> dict:
        """A JSON-safe mapping, in the shape `from_payload` reads back."""
        return {
            "source": self.source,
            "language": self.language,
            "timing_fidelity": self.timing_fidelity.value,
            "duration_seconds": self.duration_seconds,
            "text": self.text,
            "formatted_text": self.formatted_text,
            "segments": [
                {
                    "index": segment.index,
                    "start_seconds": segment.start_seconds,
                    "end_seconds": segment.end_seconds,
                    "text": segment.text,
                }
                for segment in self.segments
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "NormalizedTranscript":
        """Rebuild a transcript written by `to_payload`.

        `text` and `formatted_text` are not read back: both are derived from the
        segments, and recomputing them is what keeps a hand-edited file from claiming
        one thing in its text and another in its timings.
        """
        return cls(
            source=payload["source"],
            timing_fidelity=TimingFidelity(payload["timing_fidelity"]),
            language=payload.get("language"),
            segments=[
                TranscriptSegment(
                    index=segment["index"],
                    start_seconds=float(segment["start_seconds"]),
                    end_seconds=float(segment["end_seconds"]),
                    text=segment["text"],
                )
                for segment in payload.get("segments", [])
            ],
        )
