"""Names every memory, so a model can point at one without being shown the transcript.

This is `segment_ids.py` one stage up, and for the same reason. The model is asked only
which memories a chapter runs between, so the two memory IDs are the whole of the surface
it can get wrong: an ID either names a memory of this video or it does not, and an invented
one is caught by lookup.

What is different here is what gets rendered. A memory carries the transcript it was built
from, and none of it is sent: a chapter is a judgment about which topics belong together,
which the summaries already say, and re-sending every word of the video to decide it would
cost far more for a worse-focused prompt. So `render` lays out each memory as its ID, its
timecode and its summary, and stops there.

IDs are positional and one-based — the first memory of the video is `memory_1` — so the IDs
a reader sees in the prompt are the IDs that come back, and ordering two of them is
comparing their positions in the list.
"""

from collections.abc import Sequence

from backend.services.transcripts import SECONDS_PER_HOUR, format_timecode

from ..memories import VideoMemory

MEMORY_ID_PREFIX = "memory_"

MEMORY_LINE = "{memory_id} [{start}-{end}] {summary}"


def format_memory_id(position: int) -> str:
    """The ID of the memory at `position`, counting the first memory as `memory_1`."""
    return f"{MEMORY_ID_PREFIX}{position + 1}"


class UnknownMemoryIdError(KeyError):
    """The model returned a memory ID that is not in the list it was given."""


class MemoryIndex:
    """A video's memories, addressable by the IDs the model is shown.

    Built once per grouping and used for both directions: rendering the memories with
    their IDs attached, and resolving an ID the model returned back to the memory it
    names. Both directions read the same list, so there is no way for the IDs in the
    prompt and the IDs accepted in the response to drift apart.
    """

    def __init__(self, memories: Sequence[VideoMemory]):
        self.memories = list(memories)
        self._positions = {
            format_memory_id(position): position for position in range(len(self.memories))
        }

    @property
    def first_id(self) -> str:
        return format_memory_id(0)

    @property
    def last_id(self) -> str:
        return format_memory_id(len(self.memories) - 1)

    def __contains__(self, memory_id: str) -> bool:
        return memory_id in self._positions

    def __len__(self) -> int:
        return len(self.memories)

    def position(self, memory_id: str) -> int:
        """Where `memory_id` sits in the video, or raise if it names nothing."""
        try:
            return self._positions[memory_id]
        except KeyError:
            raise UnknownMemoryIdError(
                f"{memory_id!r} is not a memory of this video, which runs "
                f"{self.first_id} to {self.last_id}"
            ) from None

    def between(self, start_memory_id: str, end_memory_id: str) -> list[VideoMemory]:
        """The original memories from `start_memory_id` to `end_memory_id`, inclusive."""
        start = self.position(start_memory_id)
        end = self.position(end_memory_id)
        return self.memories[start : end + 1]

    def render(self) -> str:
        """The memories as `memory_1 [MM:SS-MM:SS] summary` lines, one memory each.

        Summaries only — see this module's docstring for why the transcript stays behind.
        The hour field is decided once for the whole video, as it is everywhere else, so
        every line is stamped the same width.
        """
        if not self.memories:
            return ""
        with_hours = self.memories[-1].end_seconds >= SECONDS_PER_HOUR
        return "\n".join(
            MEMORY_LINE.format(
                memory_id=format_memory_id(position),
                start=format_timecode(memory.start_seconds, with_hours=with_hours),
                end=format_timecode(memory.end_seconds, with_hours=with_hours),
                summary=memory.summary,
            )
            for position, memory in enumerate(self.memories)
        )
