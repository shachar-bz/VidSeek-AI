"""Tests for the `users` table the backend writes signup and login through."""

from contextlib import contextmanager

import psycopg
import pytest

from backend.core.errors import EmailAlreadyRegisteredError
from backend.storage.postgres import NewUser, PostgresUsers, StoredUser
from backend.storage.postgres.users import TABLE_NAME
from backend.tests.fake_postgres import FakePool

NEW_USER = NewUser(email="person@example.com", password_hash="bcrypt-hash", display_name="Person")

ROW = {
    "id": "11111111-2222-3333-4444-555555555555",
    "email": "person@example.com",
    "password_hash": "bcrypt-hash",
    "display_name": "Person",
    "created_at": "2026-09-14T10:00:00+00:00",
    "updated_at": "2026-09-14T10:00:00+00:00",
}


def _users(rows: list[dict] | None = None) -> tuple[PostgresUsers, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresUsers(pool=pool), pool


def test_a_new_account_is_inserted_and_read_back() -> None:
    users, pool = _users([ROW])
    stored = users.create(NEW_USER)

    assert f"insert into public.{TABLE_NAME}" in pool.statements[0]
    assert stored == StoredUser(
        id=ROW["id"],
        email="person@example.com",
        password_hash="bcrypt-hash",
        display_name="Person",
        created_at=ROW["created_at"],
        updated_at=ROW["updated_at"],
    )


def test_a_duplicate_email_is_reported_as_a_named_error() -> None:
    @contextmanager
    def raising_connection():
        raise psycopg.errors.UniqueViolation("duplicate key value")
        yield  # pragma: no cover - unreachable, but keeps this a generator function

    pool = FakePool(rows=[])
    pool.connection = raising_connection
    users = PostgresUsers(pool=pool)

    with pytest.raises(EmailAlreadyRegisteredError, match=NEW_USER.email):
        users.create(NEW_USER)


def test_an_insert_that_returns_no_row_is_an_error_rather_than_a_silent_success() -> None:
    users, _ = _users([])

    with pytest.raises(RuntimeError, match="returned no row"):
        users.create(NEW_USER)


def test_a_user_is_looked_up_by_email_case_insensitively() -> None:
    users, pool = _users([ROW])
    found = users.get_by_email("Person@Example.com")

    assert found is not None and found.email == "person@example.com"
    assert "lower(email) = lower(%s)" in pool.statements[0]
    assert pool.recorded[0].parameters == ("Person@Example.com",)


def test_an_unregistered_email_is_absence_rather_than_an_error() -> None:
    users, _ = _users([])

    assert users.get_by_email("nobody@example.com") is None


def test_a_user_is_looked_up_by_id() -> None:
    users, pool = _users([ROW])
    found = users.get_by_id(ROW["id"])

    assert found is not None and found.id == ROW["id"]
    assert "%s::uuid" in pool.statements[0]


def test_an_unknown_id_is_absence_rather_than_an_error() -> None:
    users, _ = _users([])

    assert users.get_by_id("00000000-0000-0000-0000-000000000000") is None
