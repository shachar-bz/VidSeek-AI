"""The `user_videos` table: one account's link to one video, and that account's own title,
tags and add time for it.

Replaces the single-owner `videos.user_id` column dropped by `migrations/0013_user_videos.sql`.
A video is a shared row; this is the many-to-many join that lets several accounts link the
same one without seeing each other's title, tags, conversations or pinned answers.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from .connection import connection, iso_text

TABLE_NAME = "user_videos"

GET_SQL = f"""
select * from public.{TABLE_NAME} where user_id = %s::uuid and video_id = %s::uuid
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredUserVideo:
    """One `user_videos` row as the database returned it."""

    user_id: str
    video_id: str
    custom_title: str | None
    tags: list[str]
    added_at: str

    @classmethod
    def from_row(cls, row: dict) -> StoredUserVideo:
        return cls(
            user_id=str(row["user_id"]),
            video_id=str(row["video_id"]),
            custom_title=row.get("custom_title"),
            tags=list(row.get("tags") or []),
            added_at=iso_text(row["added_at"]),
        )


class PostgresUserVideos:
    """The `user_videos` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def link(self, user_id: str, video_id: str) -> StoredUserVideo:
        """Add this video to this account's library, or say it is already there.

        Linking an already-linked video changes nothing about the existing link -- its
        title, tags and add time survive -- which is what lets a removed video be re-added
        later at no cost. `on conflict do nothing` followed by a plain read is what gives
        both cases the same return value without a fake self-update just to get one back.
        """
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"insert into public.{TABLE_NAME} (user_id, video_id) "
                "values (%s::uuid, %s::uuid) on conflict (user_id, video_id) do nothing",
                (user_id, video_id),
            )
            row = open_connection.execute(GET_SQL, (user_id, video_id)).fetchone()
        if row is None:
            raise RuntimeError(
                f"The {TABLE_NAME} link for user {user_id} and video {video_id} "
                "was accepted but returned no row"
            )
        stored = StoredUserVideo.from_row(row)
        logger.info("Linked video %s into user %s's library", video_id, user_id)
        return stored

    def unlink(self, user_id: str, video_id: str) -> None:
        """Remove this video from this account's library.

        The video, its transcript, chapters, memories and embeddings are untouched -- they
        belong to the video, not the link. This account's conversations and pinned answers
        for it go with the link, which the foreign keys on `conversations` handle.
        """
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where user_id = %s::uuid and video_id = %s::uuid",
                (user_id, video_id),
            )

    def get(self, user_id: str, video_id: str) -> StoredUserVideo | None:
        """This account's link to this video, or None if they have never linked it."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(GET_SQL, (user_id, video_id)).fetchone()
        return StoredUserVideo.from_row(row) if row else None

    def list_for_user(self, user_id: str) -> list[StoredUserVideo]:
        """This account's whole library, most recently added first."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} where user_id = %s::uuid "
                "order by added_at desc",
                (user_id,),
            ).fetchall()
        return [StoredUserVideo.from_row(row) for row in rows]

    def rename(self, user_id: str, video_id: str, custom_title: str | None) -> StoredUserVideo | None:
        """Set this account's own title for this video, or clear it back to the video's own.

        None when the account has no link to rename, which a route tells apart from a
        successful clear by the argument it passed rather than by this return value.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"update public.{TABLE_NAME} set custom_title = %s "
                "where user_id = %s::uuid and video_id = %s::uuid returning *",
                (custom_title, user_id, video_id),
            ).fetchone()
        return StoredUserVideo.from_row(row) if row else None

    def set_tags(self, user_id: str, video_id: str, tags: Sequence[str]) -> StoredUserVideo | None:
        """Replace this account's tags on this video with exactly `tags`.

        A full replace, the same choice `PostgresComments.replace` and
        `PostgresChapters.replace` make for their own tables: the caller already knows the
        whole set it wants, since that is what a tag editor shows.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"update public.{TABLE_NAME} set tags = %s "
                "where user_id = %s::uuid and video_id = %s::uuid returning *",
                (list(tags), user_id, video_id),
            ).fetchone()
        return StoredUserVideo.from_row(row) if row else None

    def tags_for_user(self, user_id: str) -> list[str]:
        """Every distinct tag this account has used, alphabetically.

        The suggestions a tag editor offers, per the website spec's §3.4.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select distinct tag from public.{TABLE_NAME}, unnest(tags) as tag "
                "where user_id = %s::uuid order by tag",
                (user_id,),
            ).fetchall()
        return [row["tag"] for row in rows]
