"""The `comments` table: a YouTube video's top comments, ranked by like count.

Only the YouTube pipeline ever produces comments -- the YouTube Data API is this project's
only source of them, so `backend.services.video_download.web` never has any to write and
this table simply has no rows for a non-YouTube video.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0004_comments.sql` applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from backend.services.video_download.youtube.comments import CommentEntry

from .connection import connection, iso_text

TABLE_NAME = "comments"

# The unique constraint the upsert resolves against. Must match the primary key in the
# migration: YouTube's own comment thread id, which is already unique on its own.
CONFLICT_COLUMNS = ("id",)

UPSERT_SQL = f"""
insert into public.{TABLE_NAME}
    (id, video_id, author, text, like_count, reply_count, published_at)
values (%s, %s::uuid, %s, %s, %s, %s, %s::timestamptz)
on conflict (id) do update set
    video_id = excluded.video_id,
    author = excluded.author,
    text = excluded.text,
    like_count = excluded.like_count,
    reply_count = excluded.reply_count,
    published_at = excluded.published_at
"""

logger = logging.getLogger(__name__)


class PostgresComments:
    """One video's top comments in the `comments` table."""

    def __init__(self, pool=None):
        self._pool = pool

    def replace(self, video_id: str, comments: Sequence[CommentEntry]) -> int:
        """Make this video's stored comments exactly `comments`, and say how many that is.

        Written as an upsert followed by a trim, the same as `PostgresTranscriptSegments`
        and in the same single transaction, so a re-fetch never leaves the video with no
        comments at all: every comment id is overwritten in place, and only the ids the new
        fetch did not bring back are removed.

        A like count is what this table is ordered by, so a re-fetch is worth running for
        that alone: the text of a comment rarely changes, and the number of likes on it
        always does.
        """
        rows = [_to_values(video_id, comment) for comment in comments]
        kept_ids = [row[0] for row in rows]
        with connection(self._pool) as open_connection:
            with open_connection.cursor() as cursor:
                if rows:
                    cursor.executemany(UPSERT_SQL, rows)
                # `!= all(%s)` rather than `not in (...)`: it takes the kept ids as one
                # array parameter, so an empty list is a valid value that matches every row
                # instead of a SQL syntax error, and the statement is the same either way.
                cursor.execute(
                    f"delete from public.{TABLE_NAME} "
                    "where video_id = %s::uuid and id != all(%s)",
                    (video_id, kept_ids),
                )
        logger.info("Stored %d comments for video %s", len(rows), video_id)
        return len(rows)

    def load(self, video_id: str) -> list[CommentEntry]:
        """This video's comments, best-liked first, or an empty list if it has none."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} "
                "where video_id = %s::uuid order by like_count desc",
                (video_id,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def top_liked(self, video_id: str, limit: int) -> list[CommentEntry]:
        """This video's `limit` best-liked comments, best first."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} "
                "where video_id = %s::uuid order by like_count desc limit %s",
                (video_id, limit),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def count(self, video_id: str) -> int:
        """How many comments this video has stored; zero for any non-YouTube video."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select count(*) as comment_count from public.{TABLE_NAME} "
                "where video_id = %s::uuid",
                (video_id,),
            ).fetchone()
        return int(row["comment_count"]) if row else 0

    def delete(self, video_id: str) -> None:
        """Forget this video's comments, leaving the video itself alone."""
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where video_id = %s::uuid", (video_id,)
            )


def _to_values(video_id: str, comment: CommentEntry) -> tuple:
    """One comment as the parameters of `UPSERT_SQL`, in its column order."""
    return (
        comment.id,
        video_id,
        comment.author,
        comment.text,
        comment.like_count,
        comment.reply_count,
        comment.published_at,
    )


def _from_row(row: dict) -> CommentEntry:
    return CommentEntry(
        id=row["id"],
        author=row["author"],
        text=row["text"],
        like_count=int(row["like_count"]),
        reply_count=int(row["reply_count"]),
        published_at=iso_text(row["published_at"]),
    )
