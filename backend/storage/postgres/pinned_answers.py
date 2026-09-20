"""The `pinned_answers` table: which assistant messages an account chose to keep.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0016_pinned_answers.sql` applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .connection import connection, iso_text

TABLE_NAME = "pinned_answers"

GET_SQL = f"""
select * from public.{TABLE_NAME} where message_id = %s::uuid
"""

# A pin joined out to the message it pins and that message's conversation, scoped to one
# account's one video -- the "way back to the conversation it came from" the website
# spec's §4.6 asks the pins panel to keep, without a second query per pin to get it.
LIST_FOR_VIDEO_SQL = f"""
select
    p.id as id,
    p.message_id as message_id,
    m.conversation_id as conversation_id,
    m.content as content,
    p.created_at as pinned_at
from public.{TABLE_NAME} p
join public.messages m on m.id = p.message_id
join public.conversations c on c.id = m.conversation_id
where c.user_id = %s::uuid and c.video_id = %s::uuid
order by p.created_at desc
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredPinnedAnswer:
    """One `pinned_answers` row as the database returned it, with no message content."""

    id: str
    message_id: str
    created_at: str

    @classmethod
    def from_row(cls, row: dict) -> StoredPinnedAnswer:
        return cls(
            id=str(row["id"]),
            message_id=str(row["message_id"]),
            created_at=iso_text(row["created_at"]),
        )


@dataclass(frozen=True)
class PinnedAnswerForVideo:
    """One pin as the video page's pins panel shows it: the answer, and its way back."""

    id: str
    message_id: str
    conversation_id: str
    content: str
    pinned_at: str

    @classmethod
    def from_row(cls, row: dict) -> PinnedAnswerForVideo:
        return cls(
            id=str(row["id"]),
            message_id=str(row["message_id"]),
            conversation_id=str(row["conversation_id"]),
            content=row["content"],
            pinned_at=iso_text(row["pinned_at"]),
        )


class PostgresPinnedAnswers:
    """The `pinned_answers` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def pin(self, message_id: str) -> StoredPinnedAnswer:
        """Pin one assistant message, or say it is already pinned.

        `on conflict do nothing` followed by a plain read, the same idempotent shape
        `PostgresUserVideos.link` uses: pinning an already-pinned message is not a second
        pin, so both cases hand back the one pin that exists either way.
        """
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"insert into public.{TABLE_NAME} (message_id) values (%s::uuid) "
                "on conflict (message_id) do nothing",
                (message_id,),
            )
            row = open_connection.execute(GET_SQL, (message_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"The {TABLE_NAME} pin for message {message_id} returned no row")
        return StoredPinnedAnswer.from_row(row)

    def unpin(self, message_id: str) -> None:
        """Unpin a message, leaving the message and its conversation alone."""
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where message_id = %s::uuid", (message_id,)
            )

    def list_for_video(self, user_id: str, video_id: str) -> list[PinnedAnswerForVideo]:
        """This account's pinned answers for this video, most recently pinned first."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(LIST_FOR_VIDEO_SQL, (user_id, video_id)).fetchall()
        return [PinnedAnswerForVideo.from_row(row) for row in rows]

    def pin_for_video(
        self, user_id: str, video_id: str, message_id: str
    ) -> PinnedAnswerForVideo | None:
        """Pin one owned assistant message on this video, without revealing foreign rows."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"""
                with eligible as (
                    select m.id, m.conversation_id, m.content
                    from public.messages m
                    join public.conversations c on c.id = m.conversation_id
                    where m.id = %s::uuid and m.role = 'assistant'
                      and c.user_id = %s::uuid and c.video_id = %s::uuid
                ), inserted as (
                    insert into public.{TABLE_NAME} (message_id)
                    select id from eligible
                    on conflict (message_id) do nothing
                    returning id, message_id, created_at
                )
                select p.id, p.message_id, e.conversation_id, e.content,
                       p.created_at as pinned_at
                from eligible e
                join public.{TABLE_NAME} p on p.message_id = e.id
                """,
                (message_id, user_id, video_id),
            ).fetchone()
        return PinnedAnswerForVideo.from_row(row) if row else None

    def unpin_for_video(self, user_id: str, video_id: str, message_id: str) -> bool:
        """Remove a pin only when its message belongs to this user's video conversation."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"""
                delete from public.{TABLE_NAME} p
                using public.messages m, public.conversations c
                where p.message_id = %s::uuid
                  and m.id = p.message_id and c.id = m.conversation_id
                  and c.user_id = %s::uuid and c.video_id = %s::uuid
                returning p.id
                """,
                (message_id, user_id, video_id),
            ).fetchone()
        return row is not None
