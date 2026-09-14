"""The data model of the forced alignment module.

A forced alignment times text that is already known against one media file's audio. Only
`AlignedWord.loss` needs explaining: it is the aligner's own per-word confidence, kept
exactly as the API returns it rather than reshaped into a 0-1 probability like Scribe's
`logprob`, since this is a different model reporting on a different scale.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AlignedWord:
    """One word of the original text, timed against the media it was aligned to."""

    text: str
    start_seconds: float
    end_seconds: float
    loss: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class ForcedAlignmentResult:
    """One media file's audio, timed word by word against text supplied up front."""

    media_path: str
    text: str
    loss: float
    words: list[AlignedWord] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.words)
