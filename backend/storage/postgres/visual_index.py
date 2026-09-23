"""A video's visual index: its status on `videos`, frame embeddings, segments and keyframes.

The tables are created by `migrations/0022_video_visual_index.sql`; this module only reads
and writes rows. `replace` writes a whole index at once -- every frame vector, every segment
and every keyframe, and the `ready` status with the version that built them -- in one
transaction, so a reader never sees half of an index, or an index from one model labelled
with another's version.

The status columns live on `videos` but are written only here. `PostgresVideoRecords.upsert`
does not know they exist, which is what keeps a re-recorded video from erasing them.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from .connection import connection

# The five values `videos_visual_status_known` allows, in the order a video moves through them.
PENDING = "pending"
INDEXING = "indexing"
READY = "ready"
FAILED = "failed"
SKIPPED = "skipped"
VISUAL_STATUSES = (PENDING, INDEXING, READY, FAILED, SKIPPED)

STATE_SQL = (
    "select visual_status, visual_error, visual_index_version "
    "from public.videos where id = %s::uuid"
)

# `visual_index_version` is left alone: a failed re-index does not make the version of the
# index still stored untrue, and `replace` is the only writer that changes it.
MARK_SQL = (
    "update public.videos set visual_status = %s, visual_error = %s where id = %s::uuid"
)

INSERT_FRAME_SQL = """
insert into public.video_frame_embeddings (video_id, time_seconds, embedding)
values (%s::uuid, %s, %s::vector)
"""

INSERT_SEGMENT_SQL = """
insert into public.video_visual_segments
    (video_id, segment_index, start_seconds, end_seconds, boundary_kind)
values (%s::uuid, %s, %s, %s, %s)
"""

# The segment's generated id is looked up by its position rather than read back from the
# insert, so every keyframe of the video goes in one `executemany` instead of one statement
# per segment.
INSERT_KEYFRAME_SQL = """
insert into public.video_keyframes (video_id, segment_id, time_seconds)
select %s::uuid, s.id, %s
from public.video_visual_segments s
where s.video_id = %s::uuid and s.segment_index = %s
"""

READY_SQL = """
update public.videos
set visual_status = 'ready', visual_error = null, visual_index_version = %s
where id = %s::uuid
"""

# Every frame of one video, scored against one query vector. Exhaustive on purpose: a hit is
# a frame that stands out from the rest of its own video, which cannot be judged from the
# nearest few alone. `<=>` is cosine distance, so one minus it is the cosine similarity.
FRAME_SIMILARITIES_SQL = """
select time_seconds, 1 - (embedding <=> %s::vector) as similarity
from public.video_frame_embeddings
where video_id = %s::uuid
order by time_seconds
"""

# Segments overlapping a window, each with its keyframe times. An open end on either side of
# the window is written as null, which matches everything on that side.
SEGMENTS_SQL = """
select
    s.id as segment_id,
    s.segment_index,
    s.start_seconds,
    s.end_seconds,
    s.boundary_kind,
    coalesce(
        (select array_agg(k.time_seconds order by k.time_seconds)
         from public.video_keyframes k where k.segment_id = s.id),
        '{}'
    ) as keyframe_times
from public.video_visual_segments s
where s.video_id = %s::uuid
  and (%s::double precision is null or s.end_seconds > %s)
  and (%s::double precision is null or s.start_seconds <= %s)
order by s.segment_index
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisualIndexState:
    """How far one video's visual index is, as its `videos` row records it."""

    status: str
    error: str | None
    index_version: str | None


@dataclass(frozen=True)
class NewFrameEmbedding:
    """One sampled frame's image vector, as `replace` writes it."""

    time_seconds: float
    embedding: Sequence[float]


@dataclass(frozen=True)
class NewVisualSegment:
    """One segment and its keyframe times, as `replace` writes them."""

    segment_index: int
    start_seconds: float
    end_seconds: float
    boundary_kind: str
    keyframe_times: tuple[float, ...] = ()


@dataclass(frozen=True)
class StoredVisualSegment:
    """One `video_visual_segments` row read back, with its keyframe times in order."""

    segment_id: str
    segment_index: int
    start_seconds: float
    end_seconds: float
    boundary_kind: str
    keyframe_times: tuple[float, ...]


@dataclass(frozen=True)
class FrameSimilarity:
    """How close one sampled frame is to a query vector."""

    time_seconds: float
    similarity: float


class PostgresVisualIndex:
    """One video's visual index and its status, as the rest of the backend sees them."""

    def __init__(self, pool=None):
        self._pool = pool

    def state(self, video_id: str) -> VisualIndexState | None:
        """The video's visual status, error and index version, or None if there is no such video."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(STATE_SQL, (video_id,)).fetchone()
        if row is None:
            return None
        return VisualIndexState(
            status=row["visual_status"],
            error=row.get("visual_error"),
            index_version=row.get("visual_index_version"),
        )

    def mark(self, video_id: str, status: str, *, error: str | None = None) -> None:
        """Record that the video's index moved to `status`, and why when it failed or was skipped.

        `ready` is not set here: an index is ready only together with the rows that make it
        so, which is `replace`'s job.
        """
        if status not in VISUAL_STATUSES or status == READY:
            raise ValueError(f"{status!r} is not a status `mark` can record")
        with connection(self._pool) as open_connection:
            open_connection.execute(MARK_SQL, (status, error, video_id))

    def replace(
        self,
        video_id: str,
        *,
        frames: Sequence[NewFrameEmbedding],
        segments: Sequence[NewVisualSegment],
        index_version: str,
    ) -> None:
        """Make this video's visual index exactly `frames` and `segments`, and mark it ready.

        A delete followed by inserts, all in one transaction: unlike a transcript, an index
        from another model is not partly reusable, so there is nothing to upsert in place,
        and the transaction is what keeps a reader from ever seeing the gap. Deleting the
        segments takes their keyframes with them. Saved frame captions are not touched; they
        are keyed by time and outlive a re-index.
        """
        frame_rows = [
            (video_id, frame.time_seconds, list(frame.embedding)) for frame in frames
        ]
        ordered = sorted(segments, key=lambda segment: segment.segment_index)
        segment_rows = [
            (
                video_id,
                segment.segment_index,
                segment.start_seconds,
                segment.end_seconds,
                segment.boundary_kind,
            )
            for segment in ordered
        ]
        keyframe_rows = [
            (video_id, time_seconds, video_id, segment.segment_index)
            for segment in ordered
            for time_seconds in segment.keyframe_times
        ]
        with connection(self._pool) as open_connection:
            with open_connection.cursor() as cursor:
                cursor.execute(
                    "delete from public.video_frame_embeddings where video_id = %s::uuid",
                    (video_id,),
                )
                cursor.execute(
                    "delete from public.video_visual_segments where video_id = %s::uuid",
                    (video_id,),
                )
                if frame_rows:
                    cursor.executemany(INSERT_FRAME_SQL, frame_rows)
                if segment_rows:
                    cursor.executemany(INSERT_SEGMENT_SQL, segment_rows)
                if keyframe_rows:
                    cursor.executemany(INSERT_KEYFRAME_SQL, keyframe_rows)
                cursor.execute(READY_SQL, (index_version, video_id))
        logger.info(
            "Stored a visual index of %d frames, %d segments and %d keyframes for video %s",
            len(frame_rows),
            len(segment_rows),
            len(keyframe_rows),
            video_id,
        )

    def frame_similarities(
        self, video_id: str, embedding: Sequence[float]
    ) -> list[FrameSimilarity]:
        """Every sampled frame of this video with its cosine similarity to `embedding`, in time order."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                FRAME_SIMILARITIES_SQL, (list(embedding), video_id)
            ).fetchall()
        return [
            FrameSimilarity(
                time_seconds=float(row["time_seconds"]), similarity=float(row["similarity"])
            )
            for row in rows
        ]

    def segments(
        self,
        video_id: str,
        *,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> list[StoredVisualSegment]:
        """This video's segments that overlap the window, in order; the whole video by default."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                SEGMENTS_SQL,
                (video_id, start_seconds, start_seconds, end_seconds, end_seconds),
            ).fetchall()
        return [
            StoredVisualSegment(
                segment_id=str(row["segment_id"]),
                segment_index=int(row["segment_index"]),
                start_seconds=float(row["start_seconds"]),
                end_seconds=float(row["end_seconds"]),
                boundary_kind=row["boundary_kind"],
                keyframe_times=tuple(float(value) for value in row["keyframe_times"] or ()),
            )
            for row in rows
        ]
