"""`search_visual_moments`: the frames of one video whose picture looks like what a query describes.

Every sampled frame is scored against the query with SigLIP 2's text encoder. A frame is a hit
when it stands out from the rest of the video, or scores at the present level (`scoring.py`).
Consecutive hits merge into ranges, never across a segment boundary, and each segment keeps only
its range whose best frame stood out most: one moment per shot, carrying that best frame. The
moments are ranked by how far their best frame stood out, and at most six come back.

When no frame is a hit, the search does not answer with nothing: it returns the three frames that
scored highest, each from a different segment, marked `weak`, and says that nothing stood out.
A weak frame is not a match, only the nearest thing to one, and a look decides what it shows.

On-screen text is searched by `text_search.py`, not here: this search reads the picture only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from backend.services.visual_indexing import SAMPLE_INTERVAL_SECONDS
from backend.storage.postgres import PostgresVisualIndex, StoredVisualSegment

from .moments import (
    IMAGE,
    INDEX_READY,
    FoundMoment,
    SearchContext,
    VisualSearchResult,
    fill_moments,
    open_index,
)
from .scoring import StandoutFrame, merge_into_ranges, standout_frames, z_scores

QueryEncoder = Callable[[str], list[float]]


@dataclass(frozen=True)
class MomentSearchSettings:
    """The rules the frames are read with. Starting values; the eval set tunes them."""

    # How far above its video's mean, in standard deviations, a frame must score to be a hit.
    z_threshold: float = 1.5
    # Raw SigLIP 2 cosine at which a frame is a hit even if it does not stand out, because the
    # thing is on screen for most of the video. English queries score higher than Hebrew ones.
    image_present_similarity: float = 0.15
    # How many moments a search returns at most, one per segment.
    max_moments: int = 6
    # How many of the closest frames come back, marked weak, when no frame stood out.
    weak_moments: int = 3


DEFAULT_SETTINGS = MomentSearchSettings()


def search_visual_moments(
    video_id: str,
    query: str,
    *,
    settings: MomentSearchSettings = DEFAULT_SETTINGS,
    pool=None,
    image_query_encoder: QueryEncoder | None = None,
) -> VisualSearchResult:
    """The frames of this video whose picture looks like what `query` describes, one per shot.

    The encoder defaults to the shared SigLIP 2 text encoder; a test replaces it.
    """
    opened = open_index(video_id, pool=pool)
    if isinstance(opened, VisualSearchResult):
        return opened

    if image_query_encoder is None:
        from backend.services.embeddings.image_embedding import shared_encoder

        image_query_encoder = shared_encoder().embed_text
    scored = PostgresVisualIndex(pool=pool).frame_similarities(video_id, image_query_encoder(query))
    times = [frame.time_seconds for frame in scored]
    similarities = [frame.similarity for frame in scored]

    standouts = standout_frames(
        times,
        similarities,
        z_threshold=settings.z_threshold,
        present_similarity=settings.image_present_similarity,
    )
    found = _best_moment_per_segment(opened, standouts, settings)
    nothing_stood_out = not found
    if nothing_stood_out:
        found = _weak_moments(opened, times, similarities, settings)
    return VisualSearchResult(
        index_status=INDEX_READY,
        visual_status=opened.visual_status,
        moments=fill_moments(found, opened),
        nothing_stood_out=nothing_stood_out,
        unread_keyframe_count=opened.unread_keyframe_count,
    )


def _best_moment_per_segment(
    context: SearchContext, standouts: list[StandoutFrame], settings: MomentSearchSettings
) -> list[FoundMoment]:
    """Each segment's range whose best frame stood out most, best first."""
    by_segment: dict[int, tuple[StoredVisualSegment, list[StandoutFrame]]] = {}
    for frame in standouts:
        segment = context.video_map.segment_at(frame.time_seconds)
        if segment is None:
            continue
        by_segment.setdefault(segment.segment_index, (segment, []))[1].append(frame)

    moments = []
    for segment, frames in by_segment.values():
        ranges = merge_into_ranges(frames, interval_seconds=SAMPLE_INTERVAL_SECONDS)
        best = max(ranges, key=lambda hit: (hit.peak_z_score, -hit.start_seconds))
        moments.append(
            FoundMoment(
                segment=segment,
                start_seconds=best.start_seconds,
                end_seconds=best.end_seconds,
                found_by=(IMAGE,),
                frame_seconds=best.peak_time_seconds,
                peak_z_score=best.peak_z_score,
            )
        )
    moments.sort(key=lambda moment: (-moment.peak_z_score, moment.frame_seconds))
    return moments[: settings.max_moments]


def _weak_moments(
    context: SearchContext,
    times: list[float],
    similarities: list[float],
    settings: MomentSearchSettings,
) -> list[FoundMoment]:
    """The highest-scoring frames, one per segment, marked weak: what comes back when nothing stood out."""
    frame_z_scores = z_scores(similarities)
    ranked = sorted(range(len(times)), key=lambda position: (-similarities[position], times[position]))
    moments: list[FoundMoment] = []
    segments_taken: set[int] = set()
    for position in ranked:
        if len(moments) == settings.weak_moments:
            break
        segment = context.video_map.segment_at(times[position])
        if segment is None or segment.segment_index in segments_taken:
            continue
        segments_taken.add(segment.segment_index)
        moments.append(
            FoundMoment(
                segment=segment,
                start_seconds=times[position],
                end_seconds=times[position],
                found_by=(IMAGE,),
                frame_seconds=times[position],
                peak_z_score=float(frame_z_scores[position]),
                weak=True,
            )
        )
    return moments
