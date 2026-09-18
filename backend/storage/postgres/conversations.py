"""The `conversations` table: one account's thread with the agent about one video.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0014_conversations.sql` applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg

from backend.core.errors import VideoNotLinkedError

from .connection import connection, iso_text

TABLE_NAME = "conversations"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredConversation:
    """One `conversations` row as the database returned it."""

    id: str
    user_id: str
    video_id: str
    title: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict) -> StoredConversation:
        return cls(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            video_id=str(row["video_id"]),
            title=row.get("title"),
            created_at=iso_text(row["created_at"]),
            updated_at=iso_text(row["updated_at"]),
        )


class PostgresConversations:
    """The `conversations` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def create(self, user_id: str, video_id: str, title: str | None = None) -> StoredConversation:
        """Start a new conversation thread for this account's link to this video.

        Raises `VideoNotLinkedError` rather than letting a bare foreign key violation
        surface, for the account starting a conversation about a video it has since
        removed from its library -- the link that would have justified it is gone.
        """
        try:
            with connection(self._pool) as open_connection:
                row = open_connection.execute(
                    f"insert into public.{TABLE_NAME} (user_id, video_id, title) "
                    "values (%s::uuid, %s::uuid, %s) returning *",
                    (user_id, video_id, title),
                ).fetchone()
        except psycopg.errors.ForeignKeyViolation as error:
            raise VideoNotLinkedError(video_id) from error
        if row is None:
            raise RuntimeError(f"The {TABLE_NAME} insert for video {video_id} returned no row")
        stored = StoredConversation.from_row(row)
        logger.info("Started conversation %s for user %s on video %s", stored.id, user_id, video_id)
        return stored

    def get(self, conversation_id: str) -> StoredConversation | None:
        """The conversation with this id, or None if it does not exist."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select * from public.{TABLE_NAME} where id = %s::uuid", (conversation_id,)
            ).fetchone()
        return StoredConversation.from_row(row) if row else None

    def list_for_video(self, user_id: str, video_id: str) -> list[StoredConversation]:
        """This account's conversations about this video, most recently used first."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} "
                "where user_id = %s::uuid and video_id = %s::uuid "
                "order by updated_at desc",
                (user_id, video_id),
            ).fetchall()
        return [StoredConversation.from_row(row) for row in rows]

    def rename(self, conversation_id: str, title: str) -> StoredConversation | None:
        """Set this conversation's title, or None if it does not exist."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"update public.{TABLE_NAME} set title = %s where id = %s::uuid returning *",
                (title, conversation_id),
            ).fetchone()
        return StoredConversation.from_row(row) if row else None

    def touch(self, conversation_id: str) -> None:
        """Mark this conversation as just used.

        What "most recently used first" on the video page actually sorts by. The caller
        that adds a message is expected to call this alongside `PostgresMessages.add`,
        the same way `PostgresVideoRecords.upsert` and `PostgresTranscriptSegments.replace`
        are two separate calls composed by whoever is recording a job's video.
        """
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"update public.{TABLE_NAME} set updated_at = now() where id = %s::uuid",
                (conversation_id,),
            )

    def delete(self, conversation_id: str) -> None:
        """Forget this conversation. Its messages and their pins go with it."""
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where id = %s::uuid", (conversation_id,)
            )
