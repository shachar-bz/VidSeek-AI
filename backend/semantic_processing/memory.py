"""What this stage produces: a video's transcript divided into semantic memories.

A memory holds the original `TranscriptSegment` objects it was built from, and derives its
times and its text from them. That is the whole point of the type: the only thing the
model contributes to a finished memory is `summary`, and a timestamp or a word of
transcript that the model invented has nowhere to enter. Nothing here is writable after
construction, so nothing downstream can drift from the transcript either.

Ranges are inclusive of both ends — `segments[0]` through `segments[-1]` — because a memory
is described by the two segment IDs that bound it, and both of those segments belong to it.
"""

from dataclasses import dataclass, field

from backend.services.transcripts import TranscriptSegment


@dataclass(frozen=True)
class VideoMemory:
    """One semantic moment of a video: a coherent idea, and where it was spoken.

    `start_seconds` and `end_seconds` follow the naming every other timed type in this
    project uses, and mean what the stage calls the memory's start and end time.
    """

    index: int
    start_segment_id: str
    end_segment_id: str
    summary: str
    segments: list[TranscriptSegment] = field(default_factory=list)

    @property
    def start_seconds(self) -> float:
        """When the memory's first segment begins, as the transcript measured it."""
        return self.segments[0].start_seconds

    @property
    def end_seconds(self) -> float:
        """When the memory's last segment ends, as the transcript measured it."""
        return self.segments[-1].end_seconds

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    @property
    def transcript(self) -> str:
        """The memory's speech, joined from the original segments and otherwise untouched."""
        return " ".join(segment.text for segment in self.segments)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    def to_payload(self) -> dict:
        """A JSON-safe mapping of the memory, with its derived times and text resolved."""
        return {
            "index": self.index,
            "start_segment_id": self.start_segment_id,
            "end_segment_id": self.end_segment_id,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "transcript": self.transcript,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class VideoMemories:
    """Every memory one transcript divides into, covering it end to end with no gaps.

    `source` is carried over from the transcript and `model` names what divided it, both
    for logs and for telling two runs apart later. Neither is a switch: a memory means the
    same thing whichever model produced its summaries.
    """

    source: str
    model: str
    memories: list[VideoMemory] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.memories)

    def __iter__(self):
        return iter(self.memories)

    @property
    def memory_count(self) -> int:
        return len(self.memories)

    @property
    def duration_seconds(self) -> float:
        """How far into the video the last memory ends."""
        return self.memories[-1].end_seconds if self.memories else 0.0

    def to_payload(self) -> dict:
        """A JSON-safe mapping of the whole stage's output."""
        return {
            "source": self.source,
            "model": self.model,
            "memory_count": self.memory_count,
            "duration_seconds": self.duration_seconds,
            "memories": [memory.to_payload() for memory in self.memories],
        }
