"""The `chapter_embeddings` table: one vector per chapter, for semantic search.

Reading a video's chapters for embedding is a plain read of `chapters`, unlike memories,
which need a join to reach their chapter's title; nothing else in the backend reads
`chapters` on its own yet, so there is no separate store module for that table to reuse.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0007_embeddings.sql` and
`migrations/0011_chapter_embeddings_video_times.sql` applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from .connection import connection

TABLE_NAME = "chapter_embeddings"

# The unique constraint the upsert resolves against. Must match
# `chapter_embeddings_chapter_unique` in 0007_embeddings.sql.
CONFLICT_COLUMNS = ("chapter_id",)

UPSERT_SQL = f"""
insert into public.{TABLE_NAME}
    (chapter_id, video_id, start_seconds, end_seconds, embedding, model, dimensions)
values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
on conflict (chapter_id) do update set
    video_id = excluded.video_id,
    start_seconds = excluded.start_seconds,
    end_seconds = excluded.end_seconds,
    embedding = excluded.embedding,
    model = excluded.model,
    dimensions = excluded.dimensions
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChapterForEmbedding:
    """One chapter as the embedding pipeline needs it: its own title and summary."""

    chapter_id: str
    video_id: str
    title: str
    summary: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class ChapterEmbedding:
    """One chapter's vector, and the timing it describes.

    `video_id` is not carried here: `replace` already takes it, once, for the whole batch
    it is writing, the same as `PostgresComments.replace` and `PostgresTranscriptSegments.replace`.
    """

    chapter_id: str
    start_seconds: float
    end_seconds: float
    embedding: Sequence[float]
    model: str
    dimensions: int


class PostgresChapterEmbeddings:
    """The `chapter_embeddings` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def chapters_for_video(self, video_id: str) -> list[ChapterForEmbedding]:
        """This video's chapters, in order."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                "select id as chapter_id, video_id, title, summary, "
                "start_seconds, end_seconds "
                "from public.chapters where video_id = %s::uuid order by chapter_index",
                (video_id,),
            ).fetchall()
        return [
            ChapterForEmbedding(
                chapter_id=str(row["chapter_id"]),
                video_id=str(row["video_id"]),
                title=row["title"],
                summary=row["summary"],
                start_seconds=float(row["start_seconds"]),
                end_seconds=float(row["end_seconds"]),
            )
            for row in rows
        ]

    def replace(self, video_id: str, embeddings: Sequence[ChapterEmbedding]) -> int:
        """Make this video's stored chapter embeddings exactly `embeddings`.

        Written as an upsert followed by a trim, the same as `PostgresTranscriptSegments`
        and `PostgresComments` and in the same single transaction: a re-embed overwrites
        every chapter's vector in place, and only the chapter ids the new run did not produce
        are removed, so a re-run never leaves the video with no embeddings at all.
        """
        rows = [_to_values(video_id, embedding) for embedding in embeddings]
        kept_chapter_ids = [row[0] for row in rows]
        with connection(self._pool) as open_connection:
            with open_connection.cursor() as cursor:
                if rows:
                    cursor.executemany(UPSERT_SQL, rows)
                cursor.execute(
                    f"delete from public.{TABLE_NAME} "
                    "where video_id = %s::uuid and chapter_id != all(%s)",
                    (video_id, kept_chapter_ids),
                )
        logger.info("Stored %d chapter embeddings for video %s", len(rows), video_id)
        return len(rows)

    def delete(self, video_id: str) -> None:
        """Forget this video's chapter embeddings, leaving the chapters themselves alone."""
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where video_id = %s::uuid", (video_id,)
            )


def _to_values(video_id: str, embedding: ChapterEmbedding) -> tuple:
    """One embedding as the parameters of `UPSERT_SQL`, in its column order."""
    return (
        embedding.chapter_id,
        video_id,
        embedding.start_seconds,
        embedding.end_seconds,
        list(embedding.embedding),
        embedding.model,
        embedding.dimensions,
    )
