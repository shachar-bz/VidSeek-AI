"""What the visual searches return, and the steps they share on the way to it.

The searches -- by what the picture shows (`moment_search.py`) and by the text written on screen
(`text_search.py`) -- find hits, turn them into moments inside one visual segment, and place each
moment in its segment and chapter:

* the index is opened the same way: a video whose index is not `ready`, or was built with other
  models than the current ones, is not searched, and the caller is told which it was;
* a keyframe's text stands for the stretch from that keyframe to the next keyframe of its
  segment, or to the segment's end; the matching keyframes of one segment merge into one moment;
* a picture moment carries the frame that matched best and no text: what it shows is for a look
  to say. A screen-text moment carries the text read there.

Neither search reads the transcript: the agent has its own tools for what was said.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.storage.postgres import (
    PostgresVisualIndex,
    StoredChapterOutline,
    StoredVisualSegment,
    VisualIndexState,
)
from backend.storage.postgres.visual_index import INDEXING, PENDING, READY

from .video_map import VideoVisualMap, load_video_map

# Which list found a moment, as `found_by` names it.
IMAGE = "image"
TEXT_MEANING = "text_meaning"
TEXT_CHARACTERS = "text_characters"

# Whether the index could be searched at all.
INDEX_READY = "ready"
INDEX_NOT_READY = "not_ready"
INDEX_OUTDATED = "outdated"

# Whether the agent may look at a video's picture at all, as `visual_availability` decides it:
# its index can be searched, it is still queued or being built, or it never will be as it is.
VISUAL_READY = "ready"
VISUAL_PROCESSING = "processing"
VISUAL_UNAVAILABLE = "unavailable"

# How much of a keyframe's text a screen-text moment carries. The agent looks at the frame
# when it needs the rest.
ON_SCREEN_TEXT_CHARACTERS = 400

TRUNCATION_MARK = "…"


@dataclass(frozen=True)
class VisualMoment:
    """One stretch of one segment that matched, and where it is."""

    start_seconds: float
    end_seconds: float
    segment: StoredVisualSegment
    chapter: StoredChapterOutline | None
    # The lists that found it: `image`, `text_meaning`, `text_characters`.
    found_by: tuple[str, ...]
    # The frame whose picture matched best; picture moments only.
    frame_seconds: float | None = None
    # How far that frame stood out from the rest of the video; picture moments only.
    peak_z_score: float | None = None
    # A picture moment returned although nothing stood out: one of the closest frames, not a hit.
    weak: bool = False
    # The text read on the keyframe covering the moment; screen-text moments only.
    on_screen_text: str | None = None
    # The words asked for that were found, as the caller wrote them; exact-word matches only.
    matched_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisualSearchResult:
    """What one search found, or why it could not search.

    `index_status` is `ready` when the search ran. Otherwise it is `not_ready` -- the index is
    still being built, failed, or was skipped, which `visual_status` names -- or `outdated`, an
    index built with other models than the ones this backend embeds queries with.

    `nothing_stood_out` is set by the picture search when no frame was a hit, and the moments
    are the closest frames instead, each marked `weak`.

    `unread_keyframe_count` is how many keyframes OCR has not read yet. While it is above zero,
    an on-screen text search that found nothing does not mean the text is not on screen.
    """

    index_status: str
    visual_status: str | None = None
    moments: tuple[VisualMoment, ...] = ()
    nothing_stood_out: bool = False
    unread_keyframe_count: int = 0

    @property
    def ocr_pending(self) -> bool:
        """Whether some keyframes' text has not been read yet."""
        return self.unread_keyframe_count > 0


@dataclass(frozen=True)
class SearchContext:
    """What the searches read about a video before they look for anything in it."""

    video_id: str
    visual_status: str
    video_map: VideoVisualMap
    # Every keyframe that shows text, by its time.
    keyframe_texts: Mapping[float, str]
    unread_keyframe_count: int


@dataclass(frozen=True)
class FoundMoment:
    """A moment one list found, before it is placed in its chapter and given its text."""

    segment: StoredVisualSegment
    start_seconds: float
    end_seconds: float
    found_by: tuple[str, ...]
    # The keyframe whose text the moment shows; the one covering its start when None.
    keyframe_time_seconds: float | None = None
    frame_seconds: float | None = None
    peak_z_score: float | None = None
    weak: bool = False
    matched_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeyframeTextMoment:
    """Matching keyframes of one segment, merged into the stretch their text was on screen."""

    segment: StoredVisualSegment
    start_seconds: float
    end_seconds: float
    # The matching keyframes, in time order.
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


def visual_availability(state: VisualIndexState | None) -> str:
    """Whether a video's picture can be searched and looked at, from its index state.

    Ready only as `open_index` would search it: built, with the current models. `pending` and
    `indexing` will get there; a failed or skipped index, one built with other models, or no
    video at all will not without a new indexing run.
    """
    if state is None:
        return VISUAL_UNAVAILABLE
    if state.status == READY:
        return VISUAL_READY if state.index_version == CURRENT_VISUAL_INDEX_VERSION else VISUAL_UNAVAILABLE
    if state.status in (PENDING, INDEXING):
        return VISUAL_PROCESSING
    return VISUAL_UNAVAILABLE


def keyframe_text_moments(
    keyframe_times: Iterable[float], video_map: VideoVisualMap
) -> list[KeyframeTextMoment]:
    """Matching keyframes turned into moments: one per segment, in time order.

    A keyframe's text stands for the stretch from it to the next keyframe of its segment, or to
    the segment's end. The stretches of one segment's matching keyframes merge into one moment
    that spans them all.
    """
    by_segment: dict[int, tuple[StoredVisualSegment, list[float]]] = {}
    for time_seconds in sorted(set(keyframe_times)):
        segment = segment_of_keyframe(video_map, time_seconds)
        if segment is None:
            continue
        by_segment.setdefault(segment.segment_index, (segment, []))[1].append(time_seconds)
    return [
        KeyframeTextMoment(
            segment=segment,
            start_seconds=times[0],
            end_seconds=max(keyframe_stretch_end(segment, time) for time in times),
            keyframe_times=tuple(times),
        )
        for _, (segment, times) in sorted(by_segment.items())
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


def fill_moments(found: Iterable[FoundMoment], context: SearchContext) -> tuple[VisualMoment, ...]:
    """Each found moment placed in its chapter; a screen-text moment also with the text read there."""
    moments = []
    for moment in found:
        on_screen = None
        if IMAGE not in moment.found_by:
            keyframe = moment.keyframe_time_seconds
            if keyframe is None:
                keyframe = covering_keyframe(moment.segment, moment.start_seconds)
            on_screen = context.keyframe_texts.get(keyframe) if keyframe is not None else None
        placed_at = moment.frame_seconds if moment.frame_seconds is not None else moment.start_seconds
        moments.append(
            VisualMoment(
                start_seconds=moment.start_seconds,
                end_seconds=moment.end_seconds,
                segment=moment.segment,
                chapter=context.video_map.chapter_at(placed_at),
                found_by=moment.found_by,
                frame_seconds=moment.frame_seconds,
                peak_z_score=moment.peak_z_score,
                weak=moment.weak,
                on_screen_text=capped(on_screen, ON_SCREEN_TEXT_CHARACTERS),
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


def capped(text: str | None, limit: int) -> str | None:
    """The text cut to `limit` characters, marked where it was cut; None for no text."""
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - len(TRUNCATION_MARK)].rstrip() + TRUNCATION_MARK
