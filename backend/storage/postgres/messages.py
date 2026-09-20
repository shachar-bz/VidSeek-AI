"""The `messages` table: one turn of a conversation, either side of it.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0015_messages.sql` applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from psycopg.types.json import Jsonb

from .connection import connection, iso_text

TABLE_NAME = "messages"

Role = Literal["user", "assistant"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredMessage:
    """One `messages` row as the database returned it."""

    id: str
    conversation_id: str
    role: Role
    content: str
    tool_trace: dict | list | None
    created_at: str

    @classmethod
    def from_row(cls, row: dict) -> StoredMessage:
        return cls(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            role=row["role"],
            content=row["content"],
            tool_trace=row.get("tool_trace"),
            created_at=iso_text(row["created_at"]),
        )


class PostgresMessages:
    """The `messages` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def add(
        self,
        conversation_id: str,
        role: Role,
        content: str,
        tool_trace: dict | list | None = None,
    ) -> StoredMessage:
        """Append one turn to a conversation.

        `tool_trace` is null for a user message, which called no tool, and for an
        assistant message the agent answered without needing one.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"insert into public.{TABLE_NAME} (conversation_id, role, content, tool_trace) "
                "values (%s::uuid, %s, %s, %s) returning *",
                (
                    conversation_id,
                    role,
                    content,
                    Jsonb(tool_trace) if tool_trace is not None else None,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError(
                f"The {TABLE_NAME} insert for conversation {conversation_id} returned no row"
            )
        stored = StoredMessage.from_row(row)
        logger.info("Recorded a %s message on conversation %s", role, conversation_id)
        return stored

    def get(self, message_id: str) -> StoredMessage | None:
        """The message with this id, or None if it does not exist."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select * from public.{TABLE_NAME} where id = %s::uuid", (message_id,)
            ).fetchone()
        return StoredMessage.from_row(row) if row else None

    def update_assistant(
        self,
        message_id: str,
        content: str,
        tool_trace: dict | list | None = None,
    ) -> StoredMessage | None:
        """Finalize an assistant placeholder, or return None if it no longer exists.

        The role predicate prevents this stream-finalization path from ever rewriting a
        user's turn, even if a caller supplies the wrong id.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"update public.{TABLE_NAME} set content = %s, tool_trace = %s "
                "where id = %s::uuid and role = 'assistant' returning *",
                (
                    content,
                    Jsonb(tool_trace) if tool_trace is not None else None,
                    message_id,
                ),
            ).fetchone()
        return StoredMessage.from_row(row) if row else None

    def list_for_conversation(self, conversation_id: str) -> list[StoredMessage]:
        """One conversation's full message history, in the order it was said."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} where conversation_id = %s::uuid "
                "order by created_at",
                (conversation_id,),
            ).fetchall()
        return [StoredMessage.from_row(row) for row in rows]
