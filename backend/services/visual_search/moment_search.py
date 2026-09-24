"""`search_visual_moments`: the moments of one video that show what a query describes.

Two lists are read, and never combined by score (VISUAL_UNDERSTANDING_PLAN.md §5.1):

* `image` -- every sampled frame scored against the query with SigLIP 2's text encoder. A frame
  is a hit when it stands out from the rest of the video, or scores at the present level
  (`scoring.py`). Consecutive hits merge into ranges, but never across a segment boundary.
  Ranked by how far their best frame stood out.
* `text_meaning` -- every keyframe's on-screen text scored against the query with
  multilingual-e5-small. A text is a hit when it stands out from the video's other texts; with
  too few texts for that to mean anything, the closest are taken. Ranked by the best similarity.

Each list keeps its best five moments. A picture moment and a text moment in the same segment
whose ranges overlap are one moment, found by both; those come first, and the rest alternate
between the lists by rank, picture first.

The scores are judged against the whole video even when a window is given, so a window narrows
where hits may be but not what counts as standing out: in six minutes of kitchen footage a cup is
on screen most of the time, and would stand out nowhere in them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from backend.services.visual_indexing import SAMPLE_INTERVAL_SECONDS
from backend.storage.postgres import PostgresVisualIndex, StoredVisualSegment

from .moments import (
    IMAGE,
    INDEX_READY,
    TEXT_MEANING,
    FoundMoment,
    SearchContext,
    TimeWindow,
    VisualSearchResult,
    fill_moments,
    keyframe_text_moments,
    open_index,
    ranges_overlap,
)
from .scoring import StandoutFrame, merge_into_ranges, standout_frames, standout_positions

QueryEncoder = Callable[[str], list[float]]


@dataclass(frozen=True)
class MomentSearchSettings:
    """The rules each list is read with. Starting values; the eval set tunes them."""

    # How far above its video's mean, in standard deviations, a frame or a keyframe's text must
    # score to be a hit.
    z_threshold: float = 1.5
    # Raw SigLIP 2 cosine at which a frame is a hit even if it does not stand out, because the
    # thing is on screen for most of the video. English queries score higher than Hebrew ones.
    image_present_similarity: float = 0.15
    # With fewer keyframe texts than this, a z-score over them means little, and the closest
    # are taken instead.
    minimum_texts_for_z_score: int = 20
    # How many moments each list keeps, and how many the joined list returns at most.
    moments_per_list: int = 5
    max_moments: int = 10


DEFAULT_SETTINGS = MomentSearchSettings()


def search_visual_moments(
    video_id: str,
    query: str,
    *,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    settings: MomentSearchSettings = DEFAULT_SETTINGS,
    pool=None,
    image_query_encoder: QueryEncoder | None = None,
    on_screen_text_query_encoder: QueryEncoder | None = None,
) -> VisualSearchResult:
    """The moments of this video showing what `query` describes, within the window if one is given.

    The encoders default to the shared SigLIP 2 text encoder and multilingual-e5-small; a test
    replaces them. e5 is not loaded for a video none of whose keyframes show text.
    """
    window = TimeWindow(start_seconds, end_seconds)
    opened = open_index(video_id, pool=pool)
    if isinstance(opened, VisualSearchResult):
        return opened

    picture = _picture_moments(opened, query, window, settings, pool, image_query_encoder)
    text = (
        _text_meaning_moments(opened, query, window, settings, pool, on_screen_text_query_encoder)
        if opened.keyframe_texts
        else []
    )
    found = join_lists(picture, text)[: settings.max_moments]
    return VisualSearchResult(
        index_status=INDEX_READY,
        visual_status=opened.visual_status,
        moments=fill_moments(found, opened, pool=pool),
        unread_keyframe_count=opened.unread_keyframe_count,
    )


def join_lists(picture: list[FoundMoment], text: list[FoundMoment]) -> list[FoundMoment]:
    """The two ranked lists as one, each moment once.

    A text moment and the picture moments of its segment that overlap it become one moment
    spanning them all. Those come first, ordered by the better of their two ranks and then by
    the picture's; the rest follow, alternating between the lists by rank, picture first.
    """
    joined: list[tuple[tuple[int, int], FoundMoment]] = []
    joined_picture: set[int] = set()
    joined_text: set[int] = set()
    for text_rank, text_moment in enumerate(text):
        partners = [
            (picture_rank, picture_moment)
            for picture_rank, picture_moment in enumerate(picture)
            if picture_rank not in joined_picture and ranges_overlap(picture_moment, text_moment)
        ]
        if not partners:
            continue
        joined_text.add(text_rank)
        joined_picture.update(picture_rank for picture_rank, _ in partners)
        members = [text_moment, *(moment for _, moment in partners)]
        best_picture_rank = partners[0][0]
        joined.append(
            (
                (min(best_picture_rank, text_rank), best_picture_rank),
                FoundMoment(
                    segment=text_moment.segment,
                    start_seconds=min(member.start_seconds for member in members),
                    end_seconds=max(member.end_seconds for member in members),
                    found_by=(IMAGE, TEXT_MEANING),
                    keyframe_time_seconds=text_moment.keyframe_time_seconds,
                    peak_z_score=max(moment.peak_z_score for _, moment in partners),
                ),
            )
        )
    joined.sort(key=lambda entry: entry[0])

    rest_picture = [moment for rank, moment in enumerate(picture) if rank not in joined_picture]
    rest_text = [moment for rank, moment in enumerate(text) if rank not in joined_text]
    alternating: list[FoundMoment] = []
    for position in range(max(len(rest_picture), len(rest_text))):
        alternating.extend(rest_picture[position : position + 1])
        alternating.extend(rest_text[position : position + 1])
    return [moment for _, moment in joined] + alternating


def _picture_moments(
    context: SearchContext,
    query: str,
    window: TimeWindow,
    settings: MomentSearchSettings,
    pool,
    encoder: QueryEncoder | None,
) -> list[FoundMoment]:
    """The frame ranges that stood out for the query, one segment each, best peak first."""
    if encoder is None:
        from backend.services.embeddings.image_embedding import shared_encoder

        encoder = shared_encoder().embed_text
    scored = PostgresVisualIndex(pool=pool).frame_similarities(context.video_id, encoder(query))
    standouts = standout_frames(
        [frame.time_seconds for frame in scored],
        [frame.similarity for frame in scored],
        z_threshold=settings.z_threshold,
        present_similarity=settings.image_present_similarity,
    )
    # The window is applied to the frames after they were judged against the whole video, and
    # before they merge, so a range crossing the window's edge keeps only what was seen in it.
    by_segment: dict[int, tuple[StoredVisualSegment, list[StandoutFrame]]] = {}
    for frame in standouts:
        if not window.contains(frame.time_seconds):
            continue
        segment = context.video_map.segment_at(frame.time_seconds)
        if segment is None:
            continue
        by_segment.setdefault(segment.segment_index, (segment, []))[1].append(frame)

    moments = [
        FoundMoment(
            segment=segment,
            start_seconds=hit.start_seconds,
            end_seconds=hit.end_seconds,
            found_by=(IMAGE,),
            peak_z_score=hit.peak_z_score,
        )
        for segment, frames in by_segment.values()
        for hit in merge_into_ranges(frames, interval_seconds=SAMPLE_INTERVAL_SECONDS)
    ]
    moments.sort(key=lambda moment: (-moment.peak_z_score, moment.start_seconds))
    return moments[: settings.moments_per_list]


def _text_meaning_moments(
    context: SearchContext,
    query: str,
    window: TimeWindow,
    settings: MomentSearchSettings,
    pool,
    encoder: QueryEncoder | None,
) -> list[FoundMoment]:
    """The keyframe texts that mean what the query does, one moment per segment, closest first."""
    if encoder is None:
        from backend.services.embeddings.multilingual_text_embedding import embed_query

        encoder = embed_query
    scored = PostgresVisualIndex(pool=pool).keyframe_text_similarities(
        context.video_id, encoder(query)
    )
    positions = standout_positions(
        [match.similarity for match in scored],
        z_threshold=settings.z_threshold,
        minimum_for_z_score=settings.minimum_texts_for_z_score,
    )
    similarity_at = {scored[position].time_seconds: scored[position].similarity for position in positions}

    ranked = []
    for moment in keyframe_text_moments(similarity_at, context.video_map, window):
        best_keyframe = max(moment.keyframe_times, key=lambda time: similarity_at[time])
        ranked.append(
            (
                similarity_at[best_keyframe],
                FoundMoment(
                    segment=moment.segment,
                    start_seconds=moment.start_seconds,
                    end_seconds=moment.end_seconds,
                    found_by=(TEXT_MEANING,),
                    keyframe_time_seconds=best_keyframe,
                ),
            )
        )
    ranked.sort(key=lambda entry: (-entry[0], entry[1].start_seconds))
    return [moment for _, moment in ranked[: settings.moments_per_list]]
