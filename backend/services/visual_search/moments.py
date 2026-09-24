"""What both visual searches return, and the steps they share on the way to it.

Both searches -- by what is shown (`moment_search.py`) and by the characters written on screen
(`text_search.py`) -- find hits, turn them into moments inside one visual segment, limit them to
the window asked about, and fill each moment with where it is and what surrounds it:

* the index is opened the same way: a video whose index is not `ready`, or was built with other
  models than the current ones, is not searched, and the caller is told which it was;
* a keyframe's text stands for the stretch from that keyframe to the next keyframe of its
  segment, or to the segment's end; the matching keyframes of one segment merge into one moment;
* every moment carries its segment and chapter, the on-screen text of the keyframe covering it,
  and what was said while it was on screen, read by time from the transcript.

Every moment reports plain `start_seconds`/`end_seconds`: the visual sub-agent checks its own
findings against them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.storage.postgres import (
    PostgresTranscriptSegments,
    PostgresVisualIndex,
    StoredChapterOutline,
    StoredVisualSegment,
)
from backend.storage.postgres.visual_index import READY

from .video_map import VideoVisualMap, load_video_map

# Which list found a moment, as `found_by` names it.
IMAGE = "image"
TEXT_MEANING = "text_meaning"
TEXT_CHARACTERS = "text_characters"

# Whether the index could be searched at all.
INDEX_READY = "ready"
INDEX_NOT_READY = "not_ready"
INDEX_OUTDATED = "outdated"

# How much of a keyframe's text, and of the speech around a moment, a moment carries. The
# sub-agent reads the rest with its own tools when it needs it.
ON_SCREEN_TEXT_CHARACTERS = 400
TRANSCRIPT_CHARACTERS = 600

# A moment shorter than this is read with the speech either side of it: a frame is an instant,
# and what was said about it is rarely said in the same two seconds.
SHORT_MOMENT_SECONDS = 10.0
TRANSCRIPT_WIDENING_SECONDS = 5.0

TRUNCATION_MARK = "…"


@dataclass(frozen=True)
class VisualMoment:
    """One stretch of one segment that matched, where it is, and what surrounds it."""

    start_seconds: float
    end_seconds: float
    segment: StoredVisualSegment
    chapter: StoredChapterOutline | None
    # The lists that found it: `image`, `text_meaning`, `text_characters`.
    found_by: tuple[str, ...]
    # The text read on the keyframe covering the moment, when it shows any.
    on_screen_text: str | None = None
    # What was said while it was on screen, widened for a short moment.
    transcript: str | None = None
    # How far the best frame stood out, when the picture matched.
    peak_z_score: float | None = None
    # The words asked for that were found, as the caller wrote them; `search_visual_text` only.
    matched_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisualSearchResult:
    """What one search found, or why it could not search.

    `index_status` is `ready` when the search ran. Otherwise it is `not_ready` -- the index is
    still being built, failed, or was skipped, which `visual_status` names -- or `outdated`, an
    index built with other models than the ones this backend embeds queries with.

    `unread_keyframe_count` is how many keyframes OCR has not read yet. While it is above zero,
    an on-screen text search that found nothing does not mean the text is not on screen.
    """

    index_status: str
    visual_status: str | None = None
    moments: tuple[VisualMoment, ...] = ()
    unread_keyframe_count: int = 0

    @property
    def ocr_pending(self) -> bool:
        """Whether some keyframes' text has not been read yet."""
        return self.unread_keyframe_count > 0


@dataclass(frozen=True)
class TimeWindow:
    """The part of the video a search is limited to; either end may be open."""

    start_seconds: float | None = None
    end_seconds: float | None = None

    def __post_init__(self) -> None:
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError(
                f"the window ends at {self.end_seconds}s, before it starts at {self.start_seconds}s"
            )

    def contains(self, time_seconds: float) -> bool:
        return (self.start_seconds is None or time_seconds >= self.start_seconds) and (
            self.end_seconds is None or time_seconds <= self.end_seconds
        )

    def clip(self, start_seconds: float, end_seconds: float) -> tuple[float, float] | None:
        """The part of this stretch inside the window, or None when none of it is."""
        start = start_seconds if self.start_seconds is None else max(start_seconds, self.start_seconds)
        end = end_seconds if self.end_seconds is None else min(end_seconds, self.end_seconds)
        return (start, end) if end >= start else None


@dataclass(frozen=True)
class SearchContext:
    """What both searches read about a video before they look for anything in it."""

    video_id: str
    visual_status: str
    video_map: VideoVisualMap
    # Every keyframe that shows text, by its time.
    keyframe_texts: Mapping[float, str]
    unread_keyframe_count: int


@dataclass(frozen=True)
class FoundMoment:
    """A moment one list, or both, found, before it is filled with what surrounds it."""

    segment: StoredVisualSegment
    start_seconds: float
    end_seconds: float
    found_by: tuple[str, ...]
    # The keyframe whose text the moment shows; the one covering its start when None.
    keyframe_time_seconds: float | None = None
    peak_z_score: float | None = None
    matched_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeyframeTextMoment:
    """Matching keyframes of one segment, merged into the stretch their text was on screen."""

    segment: StoredVisualSegment
    start_seconds: float
    end_seconds: float
    # The matching keyframes whose stretch reaches into the window, in time order.
    keyframe_times: tuple[float, ...]


def open_index(video_id: str, *, pool=None) -> VisualSearchResult | SearchContext:
    """The video's segments, chapters and keyframe texts, or the reason it cannot be searched."""
    store = PostgresVisualIndex(pool=pool)
    state = store.state(video_id)
    if state is None or state.status != READY:
        return VisualSearchResult(
            index_status=INDEX_NOT_READY, visual_status=state.status if state else None
        )
    if state.index_version != CURRENT_VISUAL_INDEX_VERSION:
        return VisualSearchResult(index_status=INDEX_OUTDATED, visual_status=state.status)
    video_map = load_video_map(video_id, pool=pool)
    unread = store.unread_keyframe_count(video_id)
    texts = {text.time_seconds: text.text for text in store.keyframe_texts(video_id)}
    return SearchContext(
        video_id=video_id,
        visual_status=state.status,
        video_map=video_map,
        keyframe_texts=texts,
        unread_keyframe_count=unread,
    )


def ready_video_map(video_id: str, *, pool=None) -> VideoVisualMap | None:
    """The video's segments and chapters when its index can be trusted, as `open_index` decides; None otherwise."""
    state = PostgresVisualIndex(pool=pool).state(video_id)
    if state is None or state.status != READY or state.index_version != CURRENT_VISUAL_INDEX_VERSION:
        return None
    return load_video_map(video_id, pool=pool)


def keyframe_text_moments(
    keyframe_times: Iterable[float], video_map: VideoVisualMap, window: TimeWindow
) -> list[KeyframeTextMoment]:
    """Matching keyframes turned into moments: one per segment, clipped to the window, in time order.

    A keyframe's text stands for the stretch from it to the next keyframe of its segment, or to
    the segment's end. The stretches of one segment's matching keyframes merge into one moment
    that spans them all; a keyframe whose stretch lies outside the window adds nothing.
    """
    by_segment: dict[int, tuple[StoredVisualSegment, list[tuple[float, float, float]]]] = {}
    for time_seconds in sorted(set(keyframe_times)):
        segment = segment_of_keyframe(video_map, time_seconds)
        if segment is None:
            continue
        clipped = window.clip(time_seconds, keyframe_stretch_end(segment, time_seconds))
        if clipped is None:
            continue
        entry = by_segment.setdefault(segment.segment_index, (segment, []))
        entry[1].append((time_seconds, *clipped))
    return [
        KeyframeTextMoment(
            segment=segment,
            start_seconds=min(start for _, start, _ in stretches),
            end_seconds=max(end for _, _, end in stretches),
            keyframe_times=tuple(time for time, _, _ in stretches),
        )
        for _, (segment, stretches) in sorted(by_segment.items())
    ]


def segment_of_keyframe(video_map: VideoVisualMap, time_seconds: float) -> StoredVisualSegment | None:
    """The segment a keyframe was chosen for; by time when no segment lists it."""
    for segment in video_map.segments:
        if time_seconds in segment.keyframe_times:
            return segment
    return video_map.segment_at(time_seconds)


def keyframe_stretch_end(segment: StoredVisualSegment, time_seconds: float) -> float:
    """Where a keyframe's text stops standing for the screen: the segment's next keyframe, or its end."""
    later = [keyframe for keyframe in segment.keyframe_times if keyframe > time_seconds]
    return min(later) if later else max(segment.end_seconds, time_seconds)


def ranges_overlap(first: FoundMoment, second: FoundMoment) -> bool:
    """Whether two moments are in the same segment and share at least an instant."""
    return (
        first.segment.segment_index == second.segment.segment_index
        and first.start_seconds <= second.end_seconds
        and second.start_seconds <= first.end_seconds
    )


def fill_moments(
    found: Iterable[FoundMoment], context: SearchContext, *, pool=None
) -> tuple[VisualMoment, ...]:
    """Each found moment with its chapter, its on-screen text and the speech around it."""
    transcripts = PostgresTranscriptSegments(pool=pool)
    moments = []
    for moment in found:
        keyframe = moment.keyframe_time_seconds
        if keyframe is None:
            keyframe = covering_keyframe(moment.segment, moment.start_seconds)
        on_screen = context.keyframe_texts.get(keyframe) if keyframe is not None else None
        read_from, read_to = transcript_window(moment.start_seconds, moment.end_seconds)
        spoken = " ".join(
            segment.text.strip()
            for segment in transcripts.overlapping(context.video_id, read_from, read_to)
            if segment.text.strip()
        )
        moments.append(
            VisualMoment(
                start_seconds=moment.start_seconds,
                end_seconds=moment.end_seconds,
                segment=moment.segment,
                chapter=context.video_map.chapter_at(moment.start_seconds),
                found_by=moment.found_by,
                on_screen_text=capped(on_screen, ON_SCREEN_TEXT_CHARACTERS),
                transcript=capped(spoken, TRANSCRIPT_CHARACTERS),
                peak_z_score=moment.peak_z_score,
                matched_words=moment.matched_words,
            )
        )
    return tuple(moments)


def covering_keyframe(segment: StoredVisualSegment, time_seconds: float) -> float | None:
    """The keyframe of the segment whose text is on screen at this time.

    The last keyframe at or before it; the segment's first keyframe for a time just after the
    boundary, before the first stable frame was chosen.
    """
    if not segment.keyframe_times:
        return None
    earlier = [keyframe for keyframe in segment.keyframe_times if keyframe <= time_seconds]
    return max(earlier) if earlier else min(segment.keyframe_times)


def transcript_window(start_seconds: float, end_seconds: float) -> tuple[float, float]:
    """The times to read the speech of a moment from: the moment itself, widened when it is short."""
    if end_seconds - start_seconds >= SHORT_MOMENT_SECONDS:
        return start_seconds, end_seconds
    return (
        max(0.0, start_seconds - TRANSCRIPT_WIDENING_SECONDS),
        end_seconds + TRANSCRIPT_WIDENING_SECONDS,
    )


def capped(text: str | None, limit: int) -> str | None:
    """The text cut to `limit` characters, marked where it was cut; None for no text."""
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - len(TRUNCATION_MARK)].rstrip() + TRUNCATION_MARK
