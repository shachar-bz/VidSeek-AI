"""The `comment_embeddings` table: one vector per YouTube comment, for searching them by meaning.

`replace` fills it and `nearest` is the search the conversation agent's
`get_viewer_comments` tool runs. The vectors are multilingual-e5-small's, L2-normalized, and
compared by cosine distance (`<=>`).

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0027_comment_embeddings.sql` applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from backend.services.video_download.youtube.comments import CommentEntry

from .comments import _from_row
from .connection import connection

TABLE_NAME = "comment_embeddings"

UPSERT_SQL = f"""
insert into public.{TABLE_NAME} (comment_id, video_id, embedding, model)
values (%s, %s::uuid, %s, %s)
on conflict (comment_id) do update set
    video_id = excluded.video_id,
    embedding = excluded.embedding,
    model = excluded.model
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommentEmbedding:
    """One comment's vector. `video_id` is given once, to `replace`, for the whole batch."""

    comment_id: str
    embedding: Sequence[float]
    model: str


class PostgresCommentEmbeddings:
    """The `comment_embeddings` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def replace(self, video_id: str, embeddings: Sequence[CommentEmbedding]) -> int:
        """Make this video's stored comment vectors exactly `embeddings`.

        An upsert followed by a trim in one transaction, the same as `PostgresComments.replace`.
        """
        rows = [
            (item.comment_id, video_id, list(item.embedding), item.model) for item in embeddings
        ]
        kept_ids = [row[0] for row in rows]
        with connection(self._pool) as open_connection:
            with open_connection.cursor() as cursor:
                if rows:
                    cursor.executemany(UPSERT_SQL, rows)
                cursor.execute(
                    f"delete from public.{TABLE_NAME} "
                    "where video_id = %s::uuid and comment_id != all(%s)",
                    (video_id, kept_ids),
                )
        logger.info("Stored %d comment embeddings for video %s", len(rows), video_id)
        return len(rows)

    def has_any(self, video_id: str) -> bool:
        """Whether this video's comments were embedded; false for one scanned before they were."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select exists (select 1 from public.{TABLE_NAME} "
                "where video_id = %s::uuid) as embedded",
                (video_id,),
            ).fetchone()
        return bool(row and row["embedded"])

    def nearest(self, video_id: str, embedding: Sequence[float], limit: int) -> list[CommentEntry]:
        """This video's `limit` comments closest in meaning to `embedding`, closest first.

        No similarity cutoff: on short comments e5 scores filler ("First!", "great video") as
        close to any topic as the comments actually about it, so no fixed number separates
        the two. The caller reads the shortlist and judges which comments are on topic.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                "select c.* "
                f"from public.{TABLE_NAME} e "
                "join public.comments c on c.id = e.comment_id "
                "where e.video_id = %s::uuid "
                "order by e.embedding <=> %s::vector limit %s",
                (video_id, list(embedding), limit),
            ).fetchall()
        return [_from_row(row) for row in rows]
