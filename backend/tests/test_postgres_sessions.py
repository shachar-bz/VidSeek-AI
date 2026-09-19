"""Tests for the `sessions` table: durable signed-in sessions."""

import pytest

from backend.storage.postgres import PostgresSessions, StoredSession, hash_token
from backend.storage.postgres.sessions import TABLE_NAME
from backend.tests.fake_postgres import FakePool

USER_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "22222222-2222-2222-2222-222222222222"
TOKEN = "a-secret-bearer-token"

ROW = {
    "id": SESSION_ID,
    "user_id": USER_ID,
    "token_hash": hash_token(TOKEN),
    "surface": "website",
    "created_at": "2026-09-14T10:00:00+00:00",
    "last_used_at": "2026-09-14T10:00:00+00:00",
    "expires_at": "2026-09-21T10:00:00+00:00",
}


def _sessions(rows: list[dict] | None = None) -> tuple[PostgresSessions, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresSessions(pool=pool), pool


def test_creating_a_session_stores_only_the_tokens_hash() -> None:
    sessions, pool = _sessions([ROW])
    stored = sessions.create(USER_ID, TOKEN, "website", ROW["expires_at"])

    assert f"insert into public.{TABLE_NAME}" in pool.statements[0]
    assert TOKEN not in pool.recorded[0].parameters
    assert hash_token(TOKEN) in pool.recorded[0].parameters
    assert stored == StoredSession(
        id=SESSION_ID,
        user_id=USER_ID,
        surface="website",
        created_at=ROW["created_at"],
        last_used_at=ROW["last_used_at"],
        expires_at=ROW["expires_at"],
    )


def test_a_session_that_was_not_accepted_is_an_error_rather_than_a_silent_success() -> None:
    sessions, _ = _sessions([])

    with pytest.raises(RuntimeError, match="returned no row"):
        sessions.create(USER_ID, TOKEN, "website", ROW["expires_at"])


def test_hashing_the_same_token_twice_gives_the_same_digest() -> None:
    assert hash_token(TOKEN) == hash_token(TOKEN)


def test_hashing_different_tokens_gives_different_digests() -> None:
    assert hash_token(TOKEN) != hash_token("a-different-token")


def test_verifying_a_live_token_returns_its_session_and_bumps_last_used_at() -> None:
    sessions, pool = _sessions([ROW])
    stored = sessions.verify(TOKEN)

    assert stored is not None and stored.id == SESSION_ID
    assert "set last_used_at = now()" in pool.statements[0]
    assert "expires_at > now()" in pool.statements[0]
    assert pool.recorded[0].parameters == (hash_token(TOKEN),)


def test_verifying_an_unknown_token_is_absence_rather_than_an_error() -> None:
    sessions, _ = _sessions([])

    assert sessions.verify(TOKEN) is None


def test_verifying_never_sends_the_plaintext_token_to_the_database() -> None:
    sessions, pool = _sessions([])
    sessions.verify(TOKEN)

    assert TOKEN not in pool.recorded[0].parameters


def test_a_users_sessions_come_back_most_recently_used_first() -> None:
    sessions, pool = _sessions([ROW, ROW])
    found = sessions.list_for_user(USER_ID)

    assert len(found) == 2
    assert "order by last_used_at desc" in pool.statements[0]
    assert pool.recorded[0].parameters == (USER_ID,)


def test_revoking_a_session_scopes_the_delete_to_its_owner() -> None:
    sessions, pool = _sessions([{"id": SESSION_ID}])
    revoked = sessions.revoke(USER_ID, SESSION_ID)

    assert revoked is True
    assert pool.statements[0].startswith(f"delete from public.{TABLE_NAME}")
    assert "user_id = %s::uuid" in pool.statements[0]
    assert pool.recorded[0].parameters == (SESSION_ID, USER_ID)


def test_revoking_a_session_that_does_not_belong_to_this_user_changes_nothing() -> None:
    sessions, _ = _sessions([])

    assert sessions.revoke(USER_ID, SESSION_ID) is False


def test_revoking_all_sessions_deletes_every_row_for_this_user() -> None:
    sessions, pool = _sessions([])
    sessions.revoke_all(USER_ID)

    assert pool.statements[0].startswith(f"delete from public.{TABLE_NAME}")
    assert pool.recorded[0].parameters == (USER_ID,)


def test_a_column_this_backend_does_not_know_about_is_ignored() -> None:
    stored = StoredSession.from_row({**ROW, "device_label": "Chrome on Windows"})

    assert stored.id == SESSION_ID
