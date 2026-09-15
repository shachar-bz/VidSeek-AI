"""Checks the model's grouping of the memories before anything is built from it.

Structured Outputs guarantees the shape of the response and nothing about its meaning: the
model can still return an ID that does not exist, put a chapter's end before its start,
repeat a memory in two chapters, skip one entirely, or stop short of the end of the video.
Each of those produces chapters that look fine and are wrong, and the damage only surfaces
much later — as a search result that seeks to the wrong section, or as a stretch of video
no high-level search can ever reach.

So the grouping is checked here, as a whole, before a single chapter is constructed. What
is being verified is one property in several pieces: the chapters partition the memories —
every memory belongs to exactly one chapter, in order, from the first memory to the last.
A failure raises rather than repairs, because every repair would mean guessing where a
boundary the model got wrong was meant to be.
"""

from collections.abc import Sequence

from .boundaries import ChapterBoundary
from .memory_ids import MemoryIndex, UnknownMemoryIdError, format_memory_id


class ChapterGroupingError(ValueError):
    """The model's grouping of the memories is not a usable one."""


def validate_boundaries(boundaries: Sequence[ChapterBoundary], index: MemoryIndex) -> None:
    """Raise `ChapterGroupingError` unless the boundaries partition the memories.

    The checks are made in one pass, in reading order, so the error names the first
    boundary that broke the sequence rather than reporting the damage further along.
    """
    if not index:
        raise ChapterGroupingError("The video has no memories to group.")
    if not boundaries:
        raise ChapterGroupingError("The model returned no chapters for these memories.")

    previous_start = previous_end = -1
    for position, boundary in enumerate(boundaries):
        start, end = _resolve(boundary, index, position)

        if end < start:
            raise ChapterGroupingError(
                f"Chapter {position} ends before it starts: "
                f"{boundary.start_memory_id} comes after {boundary.end_memory_id}."
            )

        if position == 0:
            if start != 0:
                raise ChapterGroupingError(
                    f"The first chapter starts at {boundary.start_memory_id}, leaving the "
                    f"memories before it in no chapter. It must start at {index.first_id}."
                )
        elif start <= previous_start:
            raise ChapterGroupingError(
                f"Chapter {position} starts at {boundary.start_memory_id}, which is not "
                f"after the start of chapter {position - 1}. Chapters must be in "
                "chronological order."
            )
        elif start <= previous_end:
            raise ChapterGroupingError(
                f"Chapter {position} starts at {boundary.start_memory_id}, which chapter "
                f"{position - 1} already covers. Chapters must not overlap."
            )
        elif start > previous_end + 1:
            raise ChapterGroupingError(
                f"Chapter {position} starts at {boundary.start_memory_id}, leaving "
                f"{_skipped_description(previous_end, start)} in no chapter. Chapters must "
                "not leave gaps."
            )

        previous_start, previous_end = start, end

    if previous_end != len(index) - 1:
        raise ChapterGroupingError(
            f"The last chapter ends at {boundaries[-1].end_memory_id}, leaving the "
            f"memories after it in no chapter. It must end at {index.last_id}."
        )


def _resolve(boundary: ChapterBoundary, index: MemoryIndex, position: int) -> tuple[int, int]:
    """Both of a boundary's memory IDs as positions, or explain which is unknown."""
    try:
        return index.position(boundary.start_memory_id), index.position(boundary.end_memory_id)
    except UnknownMemoryIdError as error:
        raise ChapterGroupingError(
            f"Chapter {position} names a memory that does not exist: {error.args[0]}"
        ) from error


def _skipped_description(previous_end: int, start: int) -> str:
    """Name the memories skipped between two chapters, as one ID or as a range."""
    first_skipped = format_memory_id(previous_end + 1)
    last_skipped = format_memory_id(start - 1)
    if first_skipped == last_skipped:
        return first_skipped
    return f"{first_skipped} to {last_skipped}"
