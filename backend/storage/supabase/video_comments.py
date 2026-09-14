"""The `video_comments` table: a YouTube video's top comments, ranked by like count.

Only the YouTube pipeline ever produces comments -- the YouTube Data API is this
project's only source of them, so `backend.services.video_download.web` never has any
to write and this table simply has no rows for a non-YouTube video.

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) in `backend/.env`,
and `migrations/0003_video_comments.sql` applied to the project.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence

from backend.services.video_download.youtube.comments import CommentEntry

from .client import build_client, shared_client
from .settings import SupabaseSettings

TABLE_NAME = "video_comments"

# The unique constraint an upsert resolves against. Must match the primary key in the
# migration: YouTube's own comment thread id, which is already unique on its own.
CONFLICT_TARGET = "id"

# How many comments go in one request. The YouTube Data API caps a video's top comments
# at 100 regardless of how many pages are read, so one batch always covers a full write.
WRITE_BATCH_ROWS = 500

logger = logging.getLogger(__name__)


class SupabaseVideoComments:
    """One video's top comments in the `video_comments` table."""

    def __init__(self, client=None, settings: SupabaseSettings | None = None):
        self._client = (
            client
            if client is not None
            else (shared_client() if settings is None else build_client(settings))
        )

    def replace(self, video_id: str, comments: Sequence[CommentEntry]) -> int:
        """Make this video's stored comments exactly `comments`, and say how many that is.

        Written as an upsert followed by a trim, the same as `SupabaseTranscriptSegments`,
        so a re-fetch never leaves the video with no comments at all: every comment id is
        overwritten in place, and only the ids the new fetch did not bring back are removed.
        """
        rows = [_to_row(video_id, comment) for comment in comments]
        for batch in _batched(rows, WRITE_BATCH_ROWS):
            self._client.table(TABLE_NAME).upsert(batch, on_conflict=CONFLICT_TARGET).execute()
        self._trim_others(video_id, [row["id"] for row in rows])
        logger.info("Stored %d comments for video %s", len(rows), video_id)
        return len(rows)

    def load(self, video_id: str) -> list[CommentEntry]:
        """This video's comments, best-liked first, or an empty list if it has none."""
        response = (
            self._client.table(TABLE_NAME)
            .select("*")
            .eq("video_id", video_id)
            .order("like_count", desc=True)
            .execute()
        )
        return [_from_row(row) for row in (response.data or [])]

    def delete(self, video_id: str) -> None:
        """Forget this video's comments, leaving the video itself alone."""
        self._client.table(TABLE_NAME).delete().eq("video_id", video_id).execute()

    def _trim_others(self, video_id: str, kept_ids: list[str]) -> None:
        """Drop whatever comments this video had that the new fetch did not bring back."""
        query = self._client.table(TABLE_NAME).delete().eq("video_id", video_id)
        if kept_ids:
            query = query.not_.in_("id", kept_ids)
        query.execute()


def _to_row(video_id: str, comment: CommentEntry) -> dict:
    return {
        "id": comment.id,
        "video_id": video_id,
        "author": comment.author,
        "text": comment.text,
        "like_count": comment.like_count,
        "reply_count": comment.reply_count,
        "published_at": comment.published_at,
    }


def _from_row(row: dict) -> CommentEntry:
    return CommentEntry(
        id=row["id"],
        author=row["author"],
        text=row["text"],
        like_count=int(row["like_count"]),
        reply_count=int(row["reply_count"]),
        published_at=row["published_at"],
    )


def _batched(rows: list[dict], size: int) -> Iterator[list[dict]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]
