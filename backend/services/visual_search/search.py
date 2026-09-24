"""Finds the moments of one video that match a text query, from everything the index knows.

Three ranked lists are read and fused by rank (`fusion.py`):

* `image` -- every sampled frame scored against the query with SigLIP 2's text encoder, kept
  only where it stands out from the rest of the video (`scoring.py`), merged into ranges;
* `caption` -- the captions the visual sub-agent saved on earlier questions, by e5 meaning;
* `transcript` -- the memories whose speech is closest to the query, by MiniLM.

On-screen text joins as two more lists (trigram and e5 over OCR text) once OCR exists; nothing
else here has to change for it.

The fusion is per visual segment. The lists do not share a granularity -- a frame is an
instant, a caption an instant or a window, a memory can run for minutes -- but every one of
them falls in some segment, and a segment is what the sub-agent navigates by. Each moment
returned is one segment: the precise ranges that matched inside it, which lists found it, and
the chapter it falls in. A range found only by the transcript is as precise as the memory,
clipped to the segment.

Search refuses an index that is not `ready` or was built with other models than the current
ones, rather than mixing vectors that cannot be compared; the caller is told which it was.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from backend.services.visual_indexing import (
    CURRENT_VISUAL_INDEX_VERSION,
    SAMPLE_INTERVAL_SECONDS,
)
from backend.storage.postgres import (
    PostgresFrameCaptions,
    PostgresMemoryEmbeddings,
    PostgresVisualIndex,
    StoredChapterOutline,
    StoredVisualSegment,
)
from backend.storage.postgres.visual_index import READY

from .fusion import reciprocal_rank_fusion
from .scoring import merge_into_ranges, standout_frames
from .video_map import VideoVisualMap, load_video_map

# The names the lists are fused under, in the order a moment reports them.
IMAGE = "image"
CAPTION = "caption"
TRANSCRIPT = "transcript"

# Whether the index could be searched at all.
INDEX_READY = "ready"
INDEX_NOT_READY = "not_ready"
INDEX_OUTDATED = "outdated"

QueryEncoder = Callable[[str], list[float]]


@dataclass(frozen=True)
class SearchSettings:
    """The cut-offs each list is read with. Starting values; the eval set tunes them.

    The floors are low on purpose. They only drop obvious junk and favour catching a match
    over precision, because the sub-agent looking at the frames is the real acceptance step.
    """

    # How far above its video's mean, in standard deviations, a frame must score to be a hit.
    z_threshold: float = 2.5
    # Raw SigLIP 2 text-to-image cosine under which a frame never counts as standing out.
    # Chance standouts on a video without the thing sit near 0.03-0.06; real matches, 0.1+.
    image_similarity_floor: float = 0.08
    # Raw cosine at which a frame is a hit even if it does not stand out, because the thing is
    # on screen for most of the video. English queries score higher than Hebrew ones.
    image_present_similarity: float = 0.15
    # e5 cosine under which a saved caption is not a match. e5's scores bunch up high --
    # right captions scored 0.81-0.94 and wrong ones up to 0.815 for the same queries -- so a
    # floor alone cannot separate them, and a caption must also be within
    # `caption_margin_from_best` of the query's best caption.
    caption_similarity_floor: float = 0.8
    caption_margin_from_best: float = 0.05
    caption_candidates: int = 10
    # MiniLM cosine under which a memory is not a match.
    transcript_similarity_floor: float = 0.3
    transcript_candidates: int = 5
    # How many moments one search returns at most.
    max_moments: int = 8


DEFAULT_SETTINGS = SearchSettings()


@dataclass(frozen=True)
class TimeRange:
    """A stretch of the video, in seconds."""

    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class VisualMoment:
    """One segment of the video that matched the query, and how.

    `start_seconds` and `end_seconds` span `matched_ranges`, which hold the precise places
    inside the segment that matched: frame ranges and caption times when the picture or a
    caption matched, the memory's overlap with the segment when only the transcript did.
    """

    start_seconds: float
    end_seconds: float
    matched_ranges: tuple[TimeRange, ...]
    sources: tuple[str, ...]
    score: float
    segment: StoredVisualSegment
    chapter: StoredChapterOutline | None
    # How far the best frame stood out, when the picture matched at all.
    peak_z_score: float | None = None
    # The saved caption that matched best, when one did.
    caption: str | None = None


@dataclass(frozen=True)
class VisualSearchResult:
    """What one search found, or why it could not search.

    `index_status` is `ready` when the search ran. Otherwise it is `not_ready` -- the index is
    still being built, failed, or was skipped, which `visual_status` names -- or `outdated`,
    an index built with other models than the ones this backend embeds queries with.

    `image_match_found` is false when no frame stood out, even if the caption or transcript
    lists found something: the picture itself gave no evidence.
    """

    index_status: str
    visual_status: str | None = None
    moments: tuple[VisualMoment, ...] = ()
    image_match_found: bool = False


@dataclass
class _Piece:
    """One list's evidence inside one segment, before fusion."""

    source: str
    rank: int
    range: TimeRange
    peak_z_score: float | None = None
    caption: str | None = None


@dataclass
class _SegmentEvidence:
    segment: StoredVisualSegment
    pieces: list[_Piece] = field(default_factory=list)


def search_visual_moments(
    video_id: str,
    query: str,
    *,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    settings: SearchSettings = DEFAULT_SETTINGS,
    pool=None,
    image_query_encoder: QueryEncoder | None = None,
    caption_query_encoder: QueryEncoder | None = None,
    transcript_query_encoder: QueryEncoder | None = None,
) -> VisualSearchResult:
    """The moments of this video matching `query`, best first, within the window if one is given.

    Frames are scored against the whole video even when a window is given, so a window
    narrows where hits may be but not what counts as standing out. The three encoders default
    to the shared SigLIP 2, multilingual-e5-small and MiniLM models; a test replaces them.
    """
    state = PostgresVisualIndex(pool=pool).state(video_id)
    if state is None or state.status != READY:
        return VisualSearchResult(
            index_status=INDEX_NOT_READY, visual_status=state.status if state else None
        )
    if state.index_version != CURRENT_VISUAL_INDEX_VERSION:
        return VisualSearchResult(index_status=INDEX_OUTDATED, visual_status=state.status)

    video_map = load_video_map(video_id, pool=pool)
    window = _Window(start_seconds, end_seconds)
    evidence: dict[int, _SegmentEvidence] = {}

    image_ranges = _image_ranges(video_id, query, settings, pool, image_query_encoder)
    for rank, hit in enumerate(image_ranges, start=1):
        _add(
            evidence,
            video_map,
            window,
            _Piece(IMAGE, rank, TimeRange(hit.start_seconds, hit.end_seconds), hit.peak_z_score),
        )
    for rank, match in enumerate(
        _caption_matches(video_id, query, settings, pool, caption_query_encoder), start=1
    ):
        caption_end = match.end_seconds if match.end_seconds is not None else match.time_seconds
        _add(
            evidence,
            video_map,
            window,
            _Piece(CAPTION, rank, TimeRange(match.time_seconds, caption_end), caption=match.caption),
        )
    for rank, match in enumerate(
        _transcript_matches(video_id, query, settings, pool, transcript_query_encoder), start=1
    ):
        _add(
            evidence,
            video_map,
            window,
            _Piece(TRANSCRIPT, rank, TimeRange(match.start_seconds, match.end_seconds)),
        )

    moments = _fuse(evidence, video_map)[: settings.max_moments]
    return VisualSearchResult(
        index_status=INDEX_READY,
        visual_status=state.status,
        moments=tuple(moments),
        # Counted after the window was applied: a frame that stood out somewhere else in the
        # video is no evidence for the part that was asked about.
        image_match_found=any(
            piece.source == IMAGE for entry in evidence.values() for piece in entry.pieces
        ),
    )


@dataclass(frozen=True)
class _Window:
    """The part of the video a search is limited to; either end may be open."""

    start: float | None
    end: float | None

    def clip(self, range_: TimeRange) -> TimeRange | None:
        start = range_.start_seconds if self.start is None else max(range_.start_seconds, self.start)
        end = range_.end_seconds if self.end is None else min(range_.end_seconds, self.end)
        return TimeRange(start, end) if end >= start else None


def _image_ranges(video_id, query, settings, pool, encoder):
    """The frame ranges that stood out for the query, best peak first."""
    if encoder is None:
        from backend.services.embeddings.image_embedding import shared_encoder

        encoder = shared_encoder().embed_text
    scored = PostgresVisualIndex(pool=pool).frame_similarities(video_id, encoder(query))
    standouts = standout_frames(
        [frame.time_seconds for frame in scored],
        [frame.similarity for frame in scored],
        z_threshold=settings.z_threshold,
        similarity_floor=settings.image_similarity_floor,
        present_similarity=settings.image_present_similarity,
    )
    ranges = merge_into_ranges(standouts, interval_seconds=SAMPLE_INTERVAL_SECONDS)
    return sorted(ranges, key=lambda hit: hit.peak_z_score, reverse=True)


def _caption_matches(video_id, query, settings, pool, encoder):
    """Saved captions above the floor, closest first; none without reading a model when there are none."""
    store = PostgresFrameCaptions(pool=pool)
    if store.count(video_id) == 0:
        return []
    if encoder is None:
        from backend.services.embeddings.multilingual_text_embedding import embed_query

        encoder = embed_query
    matches = store.similarities(video_id, encoder(query))
    if not matches:
        return []
    cutoff = max(
        settings.caption_similarity_floor,
        max(match.similarity for match in matches) - settings.caption_margin_from_best,
    )
    return [match for match in matches if match.similarity >= cutoff][: settings.caption_candidates]


def _transcript_matches(video_id, query, settings, pool, encoder):
    """Memories above the floor, closest first."""
    if encoder is None:
        from backend.services.embeddings import embed_text

        encoder = embed_text
    matches = PostgresMemoryEmbeddings(pool=pool).memory_similarities(
        video_id, encoder(query), settings.transcript_candidates
    )
    return [match for match in matches if match.similarity >= settings.transcript_similarity_floor]


def _add(
    evidence: dict[int, _SegmentEvidence],
    video_map: VideoVisualMap,
    window: _Window,
    piece: _Piece,
) -> None:
    """File one piece of evidence under every segment it overlaps, clipped to each and to the window."""
    clipped = window.clip(piece.range)
    if clipped is None:
        return
    for segment in video_map.segments_overlapping(clipped.start_seconds, clipped.end_seconds):
        inside = TimeRange(
            max(clipped.start_seconds, segment.start_seconds),
            min(clipped.end_seconds, segment.end_seconds),
        )
        entry = evidence.setdefault(segment.segment_index, _SegmentEvidence(segment))
        entry.pieces.append(
            _Piece(piece.source, piece.rank, inside, piece.peak_z_score, piece.caption)
        )


def _fuse(evidence: dict[int, _SegmentEvidence], video_map: VideoVisualMap) -> list[VisualMoment]:
    """One moment per segment with evidence, best fused score first.

    A segment's rank in a list is set by the best piece that list filed under it, ranked
    densely: segments sharing one piece -- a memory spanning three segments -- share its rank,
    and the next piece's segments come right after them.
    """
    rankings: dict[str, dict[int, int]] = {}
    for source in (IMAGE, CAPTION, TRANSCRIPT):
        best_rank_by_segment: dict[int, int] = {}
        for segment_index in sorted(evidence):
            for piece in evidence[segment_index].pieces:
                if piece.source == source:
                    best = best_rank_by_segment.get(segment_index, piece.rank)
                    best_rank_by_segment[segment_index] = min(best, piece.rank)
        distinct_ranks = sorted(set(best_rank_by_segment.values()))
        dense = {rank: position for position, rank in enumerate(distinct_ranks, start=1)}
        rankings[source] = {
            segment_index: dense[rank]
            for segment_index, rank in sorted(best_rank_by_segment.items(), key=lambda item: item[1])
        }

    moments = []
    for fused in reciprocal_rank_fusion(rankings):
        entry = evidence[fused.key]
        precise = [piece for piece in entry.pieces if piece.source in (IMAGE, CAPTION)]
        chosen = precise or entry.pieces
        ranges = tuple(
            sorted(
                {piece.range for piece in chosen},
                key=lambda range_: (range_.start_seconds, range_.end_seconds),
            )
        )
        image_peaks = [piece.peak_z_score for piece in entry.pieces if piece.peak_z_score is not None]
        captions = sorted(
            (piece for piece in entry.pieces if piece.caption is not None),
            key=lambda piece: piece.rank,
        )
        moments.append(
            VisualMoment(
                start_seconds=ranges[0].start_seconds,
                end_seconds=max(range_.end_seconds for range_ in ranges),
                matched_ranges=ranges,
                sources=fused.sources,
                score=fused.score,
                segment=entry.segment,
                chapter=video_map.chapter_at(ranges[0].start_seconds),
                peak_z_score=max(image_peaks) if image_peaks else None,
                caption=captions[0].caption if captions else None,
            )
        )
    return moments
