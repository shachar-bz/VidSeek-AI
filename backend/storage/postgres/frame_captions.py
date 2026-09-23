"""The `video_frame_captions` table: what the visual sub-agent saw when it looked at pixels.

The table is created by `migrations/0022_video_visual_index.sql`; this module only reads and
writes rows. A caption is written after an investigation that viewed a frame or a grid, so
the next question about the same part of the video can read text instead of paying for the
image again. Captions are keyed by time rather than by segment, so they survive the visual
index being rebuilt; the segment a caption falls in is worked out by whoever reads it.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from .connection import connection, iso_text

INSERT_SQL = """
insert into public.video_frame_captions
    (video_id, time_seconds, end_seconds, caption, caption_embedding, model)
values (%s::uuid, %s, %s, %s, %s::vector, %s)
"""

# Captions overlapping a window. A caption of one frame covers only its own instant, so
# `coalesce` gives it an end equal to its start. Null bounds match everything on that side.
IN_WINDOW_SQL = """
select id, time_seconds, end_seconds, caption, model, created_at
from public.video_frame_captions
where video_id = %s::uuid
  and (%s::double precision is null or coalesce(end_seconds, time_seconds) >= %s)
  and (%s::double precision is null or time_seconds <= %s)
order by time_seconds, created_at
"""

# Every caption of one video scored against a query vector, best first. Exhaustive rather
# than an ANN lookup: a video has as many captions as questions have been asked about it,
# far too few for an index to beat reading them.
SIMILARITIES_SQL = """
select id, time_seconds, end_seconds, caption,
       1 - (caption_embedding <=> %s::vector) as similarity
from public.video_frame_captions
where video_id = %s::uuid
order by caption_embedding <=> %s::vector
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewFrameCaption:
    """One caption as it is handed to `add`, already embedded."""

    time_seconds: float
    caption: str
    embedding: Sequence[float]
    model: str
    # Set for a caption of a sequence grid, which describes a window rather than one frame.
    end_seconds: float | None = None


@dataclass(frozen=True)
class StoredFrameCaption:
    """One `video_frame_captions` row read back, without its vector."""

    caption_id: str
    time_seconds: float
    end_seconds: float | None
    caption: str
    model: str
    created_at: str


@dataclass(frozen=True)
class FrameCaptionMatch:
    """One saved caption and how close it is to a query vector."""

    caption_id: str
    time_seconds: float
    end_seconds: float | None
    caption: str
    similarity: float


class PostgresFrameCaptions:
    """The `video_frame_captions` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def add(self, video_id: str, captions: Sequence[NewFrameCaption]) -> int:
        """Keep these captions for this video, and say how many were written.

        Appended rather than replaced: a caption describes what one model saw at one
        moment, and a second look at the same moment is another observation, not a
        correction the first one has to make room for.
        """
        rows = [
            (
                video_id,
                caption.time_seconds,
                caption.end_seconds,
                caption.caption,
                list(caption.embedding),
                caption.model,
            )
            for caption in captions
        ]
        if not rows:
            return 0
        with connection(self._pool) as open_connection:
            with open_connection.cursor() as cursor:
                cursor.executemany(INSERT_SQL, rows)
        logger.info("Saved %d frame captions for video %s", len(rows), video_id)
        return len(rows)

    def count(self, video_id: str) -> int:
        """How many captions this video has; zero for every video nobody has asked about yet."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                "select count(*) as caption_count from public.video_frame_captions "
                "where video_id = %s::uuid",
                (video_id,),
            ).fetchone()
        return int(row["caption_count"]) if row else 0

    def in_window(
        self,
        video_id: str,
        *,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> list[StoredFrameCaption]:
        """This video's captions that overlap the window, in time order; all of them by default."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                IN_WINDOW_SQL,
                (video_id, start_seconds, start_seconds, end_seconds, end_seconds),
            ).fetchall()
        return [
            StoredFrameCaption(
                caption_id=str(row["id"]),
                time_seconds=float(row["time_seconds"]),
                end_seconds=_optional_float(row.get("end_seconds")),
                caption=row["caption"],
                model=row["model"],
                created_at=iso_text(row["created_at"]),
            )
            for row in rows
        ]

    def similarities(
        self, video_id: str, embedding: Sequence[float]
    ) -> list[FrameCaptionMatch]:
        """Every caption of this video with its cosine similarity to `embedding`, closest first."""
        vector = list(embedding)
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                SIMILARITIES_SQL, (vector, video_id, vector)
            ).fetchall()
        return [
            FrameCaptionMatch(
                caption_id=str(row["id"]),
                time_seconds=float(row["time_seconds"]),
                end_seconds=_optional_float(row.get("end_seconds")),
                caption=row["caption"],
                similarity=float(row["similarity"]),
            )
            for row in rows
        ]


def _optional_float(value) -> float | None:
    return float(value) if value is not None else None
