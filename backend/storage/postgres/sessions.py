"""The `sessions` table: durable signed-in sessions, verified by a token's SHA-256 hash.

The table is created by `migrations/0017_sessions.sql`; this module only reads and writes
rows. As that migration explains, the token itself is never stored -- only `hash_token`'s
digest of it -- so a leaked database dump carries no live credential. Revoking a session
deletes its row rather than flipping a flag, so a revoked session and one that never existed
look identical to `verify`.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations applied.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from .connection import connection, iso_text

TABLE_NAME = "sessions"

logger = logging.getLogger(__name__)


def hash_token(token: str) -> str:
    """The SHA-256 hex digest a session's token is stored and looked up by.

    SHA-256 rather than bcrypt, for the reason `migrations/0017_sessions.sql` gives: the
    token is 256 bits of `secrets.token_urlsafe` output, so there is no low-entropy secret to
    slow an attacker down over, and bcrypt would be paid on every request rather than once
    per login.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StoredSession:
    """One `sessions` row as the database returned it. Never carries the token itself."""

    id: str
    user_id: str
    surface: str
    created_at: str
    last_used_at: str
    expires_at: str

    @classmethod
    def from_row(cls, row: dict) -> StoredSession:
        return cls(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            surface=row["surface"],
            created_at=iso_text(row["created_at"]),
            last_used_at=iso_text(row["last_used_at"]),
            expires_at=iso_text(row["expires_at"]),
        )


class PostgresSessions:
    """The `sessions` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        # Nothing here needs a setting of its own: the table name is fixed and the database
        # is baked into the pool. `pool` is accepted only so a caller (a test, most often)
        # can point one instance at a second database without touching the shared pool.
        self._pool = pool

    def create(self, user_id: str, token: str, surface: str, expires_at) -> StoredSession:
        """Start a durable session for `user_id`, storing only `token`'s hash.

        `expires_at` is supplied by the caller rather than defaulted here, so the session's
        lifetime stays a decision of `backend/core/` and is not silently duplicated in two
        places that could disagree (`migrations/0017_sessions.sql`).
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"insert into public.{TABLE_NAME} (user_id, token_hash, surface, expires_at) "
                "values (%s::uuid, %s, %s, %s) returning *",
                (user_id, hash_token(token), surface, expires_at),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"The {TABLE_NAME} insert for user {user_id} returned no row")
        stored = StoredSession.from_row(row)
        logger.info("Started %s session %s for user %s", surface, stored.id, user_id)
        return stored

    def verify(self, token: str) -> StoredSession | None:
        """The session `token` belongs to, or None if it is unknown, revoked or expired.

        Checking `expires_at` and bumping `last_used_at` in the same statement means a
        caller never has to run a second write just to keep a session's "last used" honest,
        and an expired row is rejected here rather than by a separate sweep -- nothing prunes
        this table on a timer today (`migrations/0017_sessions.sql`).
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"update public.{TABLE_NAME} set last_used_at = now() "
                "where token_hash = %s and expires_at > now() returning *",
                (hash_token(token),),
            ).fetchone()
        return StoredSession.from_row(row) if row else None

    def list_for_user(self, user_id: str) -> list[StoredSession]:
        """This account's live sessions, most recently used first.

        What the account page's session list reads (`schemas/account.py:SessionList`); a
        caller comparing each `id` against the session that verified its own request is how
        `SessionSummary.current` gets set, without this module ever handing back a token.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} where user_id = %s::uuid "
                "order by last_used_at desc",
                (user_id,),
            ).fetchall()
        return [StoredSession.from_row(row) for row in rows]

    def revoke(self, user_id: str, session_id: str) -> bool:
        """End one of this account's sessions. False if it did not exist or belongs to another.

        Scoped to `user_id` so that one account can never end a session it does not own by
        guessing another account's session id.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"delete from public.{TABLE_NAME} where id = %s::uuid and user_id = %s::uuid "
                "returning id",
                (session_id, user_id),
            ).fetchone()
        return row is not None

    def revoke_all(self, user_id: str) -> None:
        """End every session on this account, e.g. after a password change."""
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where user_id = %s::uuid", (user_id,)
            )
