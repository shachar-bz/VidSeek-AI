"""The `memory_embeddings` table: one vector per memory, for semantic search.

Reading a video's memories for embedding needs each memory's chapter title alongside it,
which is why `memories_for_video` joins `memories` to `chapters` rather than living as a
plain memory read; nothing else in the backend reads `memories` on its own yet, so there is
no separate store module for that table to reuse.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0007_embeddings.sql` and
`migrations/0010_memory_embeddings_video_chapter.sql` applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from .connection import connection

TABLE_NAME = "memory_embeddings"

# The unique constraint the upsert resolves against. Must match
# `memory_embeddings_memory_unique` in 0007_embeddings.sql.
CONFLICT_COLUMNS = ("memory_id",)

UPSERT_SQL = f"""
insert into public.{TABLE_NAME}
    (memory_id, video_id, chapter_id, embedding, model, dimensions)
values (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s)
on conflict (memory_id) do update set
    video_id = excluded.video_id,
    chapter_id = excluded.chapter_id,
    embedding = excluded.embedding,
    model = excluded.model,
    dimensions = excluded.dimensions
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryForEmbedding:
    """One memory as the embedding pipeline needs it: its own summary, and its chapter's
    title if the chapter-grouping stage has grouped it into one yet.
    """

    memory_id: str
    video_id: str
    chapter_id: str | None
    chapter_title: str | None
    summary: str


@dataclass(frozen=True)
class MemoryEmbedding:
    """One memory's vector, and the memory and chapter it describes.

    `video_id` is not carried here: `replace` already takes it, once, for the whole batch
    it is writing, the same as `PostgresComments.replace` and `PostgresTranscriptSegments.replace`.
    """

    memory_id: str
    chapter_id: str | None
    embedding: Sequence[float]
    model: str
    dimensions: int


class PostgresMemoryEmbeddings:
    """The `memory_embeddings` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def memories_for_video(self, video_id: str) -> list[MemoryForEmbedding]:
        """This video's memories, in order, each with its chapter's title if it has one.

        A memory not yet grouped into a chapter (`memories.chapter_id is null`) is still
        worth embedding on its own, so the join is a left join rather than an inner one.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                "select m.id as memory_id, m.video_id as video_id, "
                "m.chapter_id as chapter_id, c.title as chapter_title, m.summary as summary "
                "from public.memories m "
                "left join public.chapters c on c.id = m.chapter_id "
                "where m.video_id = %s::uuid order by m.memory_index",
                (video_id,),
            ).fetchall()
        return [
            MemoryForEmbedding(
                memory_id=str(row["memory_id"]),
                video_id=str(row["video_id"]),
                chapter_id=str(row["chapter_id"]) if row["chapter_id"] else None,
                chapter_title=row["chapter_title"],
                summary=row["summary"],
            )
            for row in rows
        ]

    def replace(self, video_id: str, embeddings: Sequence[MemoryEmbedding]) -> int:
        """Make this video's stored memory embeddings exactly `embeddings`.

        Written as an upsert followed by a trim, the same as `PostgresTranscriptSegments`
        and `PostgresComments` and in the same single transaction: a re-embed overwrites
        every memory's vector in place, and only the memory ids the new run did not produce
        are removed, so a re-run never leaves the video with no embeddings at all.
        """
        rows = [_to_values(video_id, embedding) for embedding in embeddings]
        kept_memory_ids = [row[0] for row in rows]
        with connection(self._pool) as open_connection:
            with open_connection.cursor() as cursor:
                if rows:
                    cursor.executemany(UPSERT_SQL, rows)
                cursor.execute(
                    f"delete from public.{TABLE_NAME} "
                    "where video_id = %s::uuid and memory_id != all(%s)",
                    (video_id, kept_memory_ids),
                )
        logger.info("Stored %d memory embeddings for video %s", len(rows), video_id)
        return len(rows)

    def delete(self, video_id: str) -> None:
        """Forget this video's memory embeddings, leaving the memories themselves alone."""
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where video_id = %s::uuid", (video_id,)
            )


def _to_values(video_id: str, embedding: MemoryEmbedding) -> tuple:
    """One embedding as the parameters of `UPSERT_SQL`, in its column order."""
    return (
        embedding.memory_id,
        video_id,
        embedding.chapter_id,
        list(embedding.embedding),
        embedding.model,
        embedding.dimensions,
    )
