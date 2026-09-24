"""A video's visual segments and chapters together, so any time can be placed in both.

Every answer the visual layer gives is a place in the video: a time range, the segment it falls
in, and the chapter around it -- "04:12-04:30, chapter 'Preparing the sauce'". The segments come
from the visual index and the chapters from transcript segmentation, which ran separately and
in parallel, so the two are joined here, by time, rather than by a key either stage wrote.

A scene is a run of segments between two cuts: a `text_change` boundary (a new slide, a
board written on) stays inside the scene, and any other boundary starts a new one.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from backend.services.visual_indexing.segments import TEXT_CHANGE
from backend.storage.postgres import (
    PostgresChapters,
    PostgresVisualIndex,
    StoredChapterOutline,
    StoredVisualSegment,
)


@dataclass(frozen=True)
class VideoVisualMap:
    """One video's segments and chapters, each in time order."""

    segments: tuple[StoredVisualSegment, ...]
    chapters: tuple[StoredChapterOutline, ...]

    def segment_at(self, time_seconds: float) -> StoredVisualSegment | None:
        """The segment showing at this time; the last one for a time past the end."""
        return _latest_starting_at_or_before(self.segments, time_seconds)

    def chapter_at(self, time_seconds: float) -> StoredChapterOutline | None:
        """The chapter this time falls in, or None before the first chapter or with none at all."""
        return _latest_starting_at_or_before(self.chapters, time_seconds)

    def segments_overlapping(
        self, start_seconds: float, end_seconds: float
    ) -> list[StoredVisualSegment]:
        """Every segment the window touches, in order. A zero-length window touches one."""
        if end_seconds <= start_seconds:
            found = self.segment_at(start_seconds)
            return [found] if found is not None else []
        return [
            segment
            for segment in self.segments
            if segment.start_seconds < end_seconds and segment.end_seconds > start_seconds
        ]

    def scene_at(self, time_seconds: float) -> tuple[float, float] | None:
        """The start and end of the scene showing at this time, or None with no segments."""
        found = self.segment_at(time_seconds)
        if found is None:
            return None
        position = self.segments.index(found)
        first = position
        while first > 0 and self.segments[first].boundary_kind == TEXT_CHANGE:
            first -= 1
        last = position
        while last + 1 < len(self.segments) and self.segments[last + 1].boundary_kind == TEXT_CHANGE:
            last += 1
        return self.segments[first].start_seconds, self.segments[last].end_seconds


def load_video_map(video_id: str, *, pool=None) -> VideoVisualMap:
    """Read one video's segments and chapter outline."""
    return VideoVisualMap(
        segments=tuple(PostgresVisualIndex(pool=pool).segments(video_id)),
        chapters=tuple(PostgresChapters(pool=pool).video_outline(video_id)),
    )


def _latest_starting_at_or_before(items, time_seconds: float):
    """The last of `items` (sorted by start) that starts at or before the time."""
    if not items:
        return None
    position = bisect_right([item.start_seconds for item in items], time_seconds)
    return items[position - 1] if position > 0 else None
