"""Password hashing and the durable bearer tokens a signed-in user's requests carry.

This is a separate concept from `SessionRegistry` in `core.security`, which proves a
request came from an allowed Chrome extension installation, not from any particular person.
`UserAuthRegistry` proves the opposite: which account, if any, is signed in. The two tokens
travel in the same `Authorization: Bearer` header shape but are never compared against each
other, so a route can require one, the other, both or neither.

Tokens are backed by the `sessions` table (`backend.storage.postgres.sessions`) rather than
an in-process dictionary, so one sign-in is recognised by both the website and the Chrome
extension and survives a process restart. `core/` imports no other project package, so that
store is described here by the `SessionsStore` protocol and handed in by `api/`.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Protocol

import bcrypt

# Long enough that a signed-in user is not asked to log in again every time they return,
# short enough that a token copied out of storage does not stay valid forever.
AUTH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60

# bcrypt silently ignores any byte past 72, so a longer password would compare equal to a
# truncated one without this; the request is rejected instead, at the schema layer.
MAX_PASSWORD_LENGTH = 72


def normalize_email(email: str) -> str:
    """The form an email is stored and looked up under: trimmed and lower-cased."""
    return email.strip().lower()


def hash_password(password: str) -> str:
    """A bcrypt hash of `password`, salted, safe to store."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Whether `password` is the one `password_hash` was generated from."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # A hash written in a shape bcrypt does not recognize; never mistake that for a match.
        return False


class SessionRecord(Protocol):
    """The parts of one stored session this module reads."""

    id: str
    user_id: str


class SessionsStore(Protocol):
    """Durable session storage, as `PostgresSessions` provides it."""

    def create(self, user_id: str, token: str, surface: str, expires_at) -> SessionRecord: ...

    def verify(self, token: str) -> SessionRecord | None: ...

    def revoke(self, user_id: str, session_id: str) -> bool: ...


class UserAuthRegistry:
    """Issues and verifies the bearer tokens login and signup hand back, via `sessions`.

    The raw token is generated and returned here, once, and never stored: `PostgresSessions`
    persists only its SHA-256 digest, so a leaked database dump carries no live credential.
    """

    def __init__(
        self,
        sessions_store: SessionsStore,
        ttl_seconds: int = AUTH_TOKEN_TTL_SECONDS,
    ):
        self._sessions = sessions_store
        self._ttl_seconds = ttl_seconds

    def issue(self, user_id: str, surface: str) -> str:
        """A fresh token bound to `user_id` and `surface`, replacing none of that user's
        other sessions."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
        self._sessions.create(user_id, token, surface, expires_at)
        return token

    def verify(self, token: str) -> SessionRecord | None:
        """The live session `token` belongs to, or None if it is unknown, expired or revoked.

        `PostgresSessions.verify` bumps `last_used_at` in the same statement that checks
        expiry, so there is no separate bookkeeping write whose failure could be mistaken for
        a successful authorization: the check and the update either both happen or neither
        does.
        """
        if not token:
            return None
        return self._sessions.verify(token)

    def revoke(self, token: str) -> None:
        """End the session `token` belongs to, for logout. An unknown token is not an error."""
        if not token:
            return
        stored = self._sessions.verify(token)
        if stored:
            self._sessions.revoke(stored.user_id, stored.id)
