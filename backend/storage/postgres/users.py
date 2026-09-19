"""The `users` table: the email and password hash a VidSeek account signs in with.

The table is created by `migrations/0008_users.sql`; this module only reads and writes
rows. Nothing else in this database points at a user yet -- `videos`, `transcript_segments`
and `comments` are keyed the same way they always were -- so this module stands on its own.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg

from backend.core.errors import EmailAlreadyRegisteredError

from .connection import connection, iso_text

TABLE_NAME = "users"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewUser:
    """An account as it is handed to `create`. The password has already been hashed."""

    email: str
    password_hash: str
    display_name: str | None = None


@dataclass(frozen=True)
class StoredUser:
    """One `users` row as the database returned it."""

    id: str
    email: str
    password_hash: str
    display_name: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict) -> StoredUser:
        return cls(
            id=str(row["id"]),
            email=row["email"],
            password_hash=row["password_hash"],
            display_name=row.get("display_name"),
            created_at=iso_text(row["created_at"]),
            updated_at=iso_text(row["updated_at"]),
        )


class PostgresUsers:
    """The `users` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        # Nothing here needs a setting of its own: the table name is fixed and the database
        # is baked into the pool. `pool` is accepted only so a caller (a test, most often)
        # can point one instance at a second database without touching the shared pool.
        self._pool = pool

    def create(self, user: NewUser) -> StoredUser:
        """Insert a new account.

        Raises `EmailAlreadyRegisteredError` rather than letting a bare `psycopg.Error`
        surface, so a route can tell "this email is taken" apart from every other way an
        insert can fail without inspecting a driver exception itself.
        """
        try:
            with connection(self._pool) as open_connection:
                row = open_connection.execute(
                    f"insert into public.{TABLE_NAME} (email, password_hash, display_name) "
                    "values (%s, %s, %s) returning *",
                    (user.email, user.password_hash, user.display_name),
                ).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise EmailAlreadyRegisteredError(user.email) from error
        if row is None:
            raise RuntimeError(f"The {TABLE_NAME} insert for {user.email} returned no row")
        stored = StoredUser.from_row(row)
        logger.info("Registered user %s as %s", user.email, stored.id)
        return stored

    def get_by_email(self, email: str) -> StoredUser | None:
        """The account registered under `email`, case-insensitively, or None."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select * from public.{TABLE_NAME} where lower(email) = lower(%s) limit 1",
                (email,),
            ).fetchone()
        return StoredUser.from_row(row) if row else None

    def get_by_id(self, user_id: str) -> StoredUser | None:
        """The account with this id, or None if it no longer exists."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select * from public.{TABLE_NAME} where id = %s::uuid limit 1",
                (user_id,),
            ).fetchone()
        return StoredUser.from_row(row) if row else None

    def update_display_name(self, user_id: str, display_name: str) -> StoredUser | None:
        """Change the account's display name, returning None if it disappeared."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"update public.{TABLE_NAME} set display_name = %s "
                "where id = %s::uuid returning *",
                (display_name, user_id),
            ).fetchone()
        return StoredUser.from_row(row) if row else None

    def update_password_hash(self, user_id: str, password_hash: str) -> bool:
        """Replace an account's bcrypt hash without ever handling its plaintext password."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"update public.{TABLE_NAME} set password_hash = %s "
                "where id = %s::uuid returning id",
                (password_hash, user_id),
            ).fetchone()
        return row is not None

    def delete(self, user_id: str) -> bool:
        """Delete an account; database foreign keys remove only its private descendants."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"delete from public.{TABLE_NAME} where id = %s::uuid returning id",
                (user_id,),
            ).fetchone()
        return row is not None
