"""What this stage produces: a video's memories grouped into semantic chapters.

A chapter holds the original `VideoMemory` objects it was built from, and derives its times
from them. That is the whole point of the type: the only things the model contributes to a
finished chapter are `title` and `summary`, and a timestamp the model invented has nowhere
to enter — it was never asked for one. Nothing here is writable after construction, so
nothing downstream can drift from the memories either.

Ranges are inclusive of both ends — `memories[0]` through `memories[-1]` — because a chapter
is described by the two memory IDs that bound it, and both of those memories belong to it.
"""

from dataclasses import dataclass, field

from ..memories import VideoMemory


@dataclass(frozen=True)
class VideoChapter:
    """One broad section of a video: several related memories, and where they were spoken.

    `start_seconds` and `end_seconds` follow the naming every other timed type in this
    project uses, and mean what the stage calls the chapter's start and end time.
    """

    index: int
    start_memory_id: str
    end_memory_id: str
    title: str
    summary: str
    memories: list[VideoMemory] = field(default_factory=list)

    @property
    def start_seconds(self) -> float:
        """When the chapter's first memory begins, as the transcript measured it."""
        return self.memories[0].start_seconds

    @property
    def end_seconds(self) -> float:
        """When the chapter's last memory ends, as the transcript measured it."""
        return self.memories[-1].end_seconds

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    @property
    def memory_count(self) -> int:
        return len(self.memories)

    @property
    def transcript(self) -> str:
        """The chapter's speech, joined from the memories it covers and otherwise untouched."""
        return " ".join(memory.transcript for memory in self.memories)

    def to_payload(self) -> dict:
        """A JSON-safe mapping of the chapter, with its derived times resolved."""
        return {
            "index": self.index,
            "start_memory_id": self.start_memory_id,
            "end_memory_id": self.end_memory_id,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "title": self.title,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class VideoChapters:
    """Every chapter one video's memories group into, covering them end to end with no gaps.

    `source` is carried over from the memories and `model` names what grouped them, both
    for logs and for telling two runs apart later. Neither is a switch: a chapter means the
    same thing whichever model titled it.
    """

    source: str
    model: str
    chapters: list[VideoChapter] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.chapters)

    def __iter__(self):
        return iter(self.chapters)

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)

    @property
    def duration_seconds(self) -> float:
        """How far into the video the last chapter ends."""
        return self.chapters[-1].end_seconds if self.chapters else 0.0

    def to_payload(self) -> dict:
        """A JSON-safe mapping of the whole stage's output."""
        return {
            "source": self.source,
            "model": self.model,
            "chapter_count": self.chapter_count,
            "duration_seconds": self.duration_seconds,
            "chapters": [chapter.to_payload() for chapter in self.chapters],
        }
