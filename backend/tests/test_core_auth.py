"""Tests for password hashing and the durable user auth token registry.

`UserAuthRegistry` is tested here against a fake standing in for `PostgresSessions`, so
these stay unit tests of the wiring -- issuing a token records the right surface, verifying
delegates to the store, revoking looks a token's session up first -- rather than a second
copy of `test_postgres_sessions.py`, which already covers the SQL the durable store runs.
"""

from __future__ import annotations

from backend.core.auth import UserAuthRegistry, hash_password, normalize_email, verify_password
from backend.storage.postgres.sessions import StoredSession

EXPIRES_AT = "2026-10-14T10:00:00+00:00"


class FakeSessionsStore:
    """Stands in for `PostgresSessions`: keeps sessions by token, in memory."""

    def __init__(self) -> None:
        self.create_calls: list[tuple[str, str, str, object]] = []
        self.revoke_calls: list[tuple[str, str]] = []
        self._sessions_by_token: dict[str, StoredSession] = {}
        self._next_id = 1

    def create(self, user_id: str, token: str, surface: str, expires_at: object) -> StoredSession:
        self.create_calls.append((user_id, token, surface, expires_at))
        session = StoredSession(
            id=f"session-{self._next_id}",
            user_id=user_id,
            surface=surface,
            created_at="2026-09-14T10:00:00+00:00",
            last_used_at="2026-09-14T10:00:00+00:00",
            expires_at=str(expires_at),
        )
        self._next_id += 1
        self._sessions_by_token[token] = session
        return session

    def verify(self, token: str) -> StoredSession | None:
        return self._sessions_by_token.get(token)

    def revoke(self, user_id: str, session_id: str) -> bool:
        self.revoke_calls.append((user_id, session_id))
        for token, session in list(self._sessions_by_token.items()):
            if session.id == session_id and session.user_id == user_id:
                del self._sessions_by_token[token]
                return True
        return False


def test_a_password_verifies_against_its_own_hash() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_the_wrong_password_does_not_verify() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_two_hashes_of_the_same_password_are_not_identical() -> None:
    # bcrypt salts every hash, which is what stops two accounts sharing a password from
    # showing it in the stored hash.
    assert hash_password("shared password") != hash_password("shared password")


def test_a_malformed_hash_never_verifies() -> None:
    assert not verify_password("anything", "not a bcrypt hash")


def test_email_is_normalized_to_trimmed_lowercase() -> None:
    assert normalize_email("  User@Example.com  ") == "user@example.com"


def test_issuing_a_token_persists_it_to_the_sessions_store_with_its_surface() -> None:
    store = FakeSessionsStore()
    registry = UserAuthRegistry(store)
    token = registry.issue("user-1", "website")
    assert store.create_calls == [("user-1", token, "website", store.create_calls[0][3])]


def test_a_token_verifies_to_the_session_it_was_issued_for() -> None:
    registry = UserAuthRegistry(FakeSessionsStore())
    token = registry.issue("user-1", "extension")
    session = registry.verify(token)
    assert session is not None
    assert session.user_id == "user-1"
    assert session.surface == "extension"


def test_an_unknown_token_does_not_verify() -> None:
    registry = UserAuthRegistry(FakeSessionsStore())
    assert registry.verify("not-a-real-token") is None


def test_an_empty_token_does_not_verify() -> None:
    registry = UserAuthRegistry(FakeSessionsStore())
    assert registry.verify("") is None


def test_a_revoked_token_no_longer_verifies() -> None:
    registry = UserAuthRegistry(FakeSessionsStore())
    token = registry.issue("user-1", "website")
    registry.revoke(token)
    assert registry.verify(token) is None


def test_revoking_a_token_ends_the_session_it_named_rather_than_every_session() -> None:
    store = FakeSessionsStore()
    registry = UserAuthRegistry(store)
    first = registry.issue("user-1", "website")
    second = registry.issue("user-1", "extension")
    registry.revoke(first)
    assert registry.verify(first) is None
    assert registry.verify(second) is not None


def test_revoking_an_unknown_token_is_not_an_error() -> None:
    UserAuthRegistry(FakeSessionsStore()).revoke("never-issued")


def test_revoking_an_empty_token_is_not_an_error() -> None:
    UserAuthRegistry(FakeSessionsStore()).revoke("")


def test_two_issued_tokens_for_the_same_user_are_both_valid() -> None:
    # Logging in from a second machine, or from the website and the extension, must not
    # sign the first session out.
    registry = UserAuthRegistry(FakeSessionsStore())
    first = registry.issue("user-1", "website")
    second = registry.issue("user-1", "extension")
    assert registry.verify(first).user_id == "user-1"
    assert registry.verify(second).user_id == "user-1"
