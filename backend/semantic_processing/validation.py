"""Checks the model's division of a transcript before anything is built from it.

Structured Outputs guarantees the shape of the response and nothing about its meaning: the
model can still return an ID that does not exist, put a memory's end before its start,
repeat a segment in two memories, skip one entirely, or stop short of the end of the video.
Each of those produces memories that look fine and are wrong, and the damage only surfaces
much later — as a search result that seeks to the wrong moment, or as a stretch of video no
search can ever reach.

So the division is checked here, as a whole, before a single memory is constructed. What is
being verified is one property in several pieces: the memories partition the transcript —
every segment belongs to exactly one memory, in order, from the first segment to the last.
A failure raises rather than repairs, because every repair would mean guessing where a
boundary the model got wrong was meant to be.
"""

from collections.abc import Sequence

from .boundaries import MemoryBoundary
from .segment_ids import SegmentIndex, UnknownSegmentIdError, format_segment_id


class MemorySegmentationError(ValueError):
    """The model's division of the transcript is not a usable one."""


def validate_boundaries(boundaries: Sequence[MemoryBoundary], index: SegmentIndex) -> None:
    """Raise `MemorySegmentationError` unless the boundaries partition the transcript.

    The checks are made in one pass, in reading order, so the error names the first
    boundary that broke the sequence rather than reporting the damage further along.
    """
    if not index:
        raise MemorySegmentationError("The transcript has no segments to divide.")
    if not boundaries:
        raise MemorySegmentationError("The model returned no memories for this transcript.")

    previous_start = previous_end = -1
    for position, boundary in enumerate(boundaries):
        start, end = _resolve(boundary, index, position)

        if end < start:
            raise MemorySegmentationError(
                f"Memory {position} ends before it starts: "
                f"{boundary.start_segment_id} comes after {boundary.end_segment_id}."
            )

        if position == 0:
            if start != 0:
                raise MemorySegmentationError(
                    f"The first memory starts at {boundary.start_segment_id}, leaving the "
                    f"transcript before it in no memory. It must start at {index.first_id}."
                )
        elif start <= previous_start:
            raise MemorySegmentationError(
                f"Memory {position} starts at {boundary.start_segment_id}, which is not "
                f"after the start of memory {position - 1}. Memories must be in "
                "chronological order."
            )
        elif start <= previous_end:
            raise MemorySegmentationError(
                f"Memory {position} starts at {boundary.start_segment_id}, which memory "
                f"{position - 1} already covers. Memories must not overlap."
            )
        elif start > previous_end + 1:
            raise MemorySegmentationError(
                f"Memory {position} starts at {boundary.start_segment_id}, leaving "
                f"{_skipped_description(previous_end, start)} in no memory. Memories must "
                "not leave gaps."
            )

        previous_start, previous_end = start, end

    if previous_end != len(index) - 1:
        raise MemorySegmentationError(
            f"The last memory ends at {boundaries[-1].end_segment_id}, leaving the "
            f"transcript after it in no memory. It must end at {index.last_id}."
        )


def _resolve(boundary: MemoryBoundary, index: SegmentIndex, position: int) -> tuple[int, int]:
    """Both of a boundary's segment IDs as transcript positions, or explain which is unknown."""
    try:
        return index.position(boundary.start_segment_id), index.position(boundary.end_segment_id)
    except UnknownSegmentIdError as error:
        raise MemorySegmentationError(
            f"Memory {position} names a segment that does not exist: {error.args[0]}"
        ) from error


def _skipped_description(previous_end: int, start: int) -> str:
    """Name the segments skipped between two memories, as one ID or as a range."""
    first_skipped = format_segment_id(previous_end + 1)
    last_skipped = format_segment_id(start - 1)
    if first_skipped == last_skipped:
        return first_skipped
    return f"{first_skipped} to {last_skipped}"
