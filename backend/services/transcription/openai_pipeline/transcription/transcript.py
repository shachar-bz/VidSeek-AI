"""The transcript data model shared by the OpenAI transcription module.

A transcript is a list of chunks, each covering a half-open time range of the source
video. Word-level timing is optional: `gpt-transcribe` returns no timestamps of any kind,
so `TranscriptWord` stays empty until a separate forced-alignment pass fills it in.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranscriptWord:
    """One spoken word, timed against the source video rather than against its chunk."""

    text: str
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class TranscriptChunk:
    """The transcript of one half-open time range [start_seconds, end_seconds) of a video.

    A video short enough to transcribe in a single API request produces exactly one chunk
    spanning the whole video, so `start_seconds` is 0 and the chunk carries no seek
    granularity of its own. Longer videos are split, and then each chunk's range is the
    finest timing the transcript offers until words are aligned.
    """

    index: int
    start_seconds: float
    end_seconds: float
    text: str
    languages: list[str] = field(default_factory=list)
    words: list[TranscriptWord] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class TranscriptionResult:
    """Everything transcribed from one video, in chunk order."""

    video_path: str
    duration_seconds: float
    model: str
    chunks: list[TranscriptChunk] = field(default_factory=list)

    @property
    def text(self) -> str:
        """The whole transcript as one string, chunks joined in time order."""
        return " ".join(chunk.text.strip() for chunk in self.chunks if chunk.text.strip())

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def has_word_timestamps(self) -> bool:
        """True once a forced-alignment pass has filled in per-word timing."""
        return any(chunk.words for chunk in self.chunks)

    @property
    def words(self) -> list[TranscriptWord]:
        """Every aligned word across all chunks, in time order. Empty before alignment."""
        return [word for chunk in self.chunks for word in chunk.words]
