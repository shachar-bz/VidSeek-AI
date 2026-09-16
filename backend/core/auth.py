"""Password hashing and the bearer tokens a logged-in user's requests carry.

This is a separate concept from `SessionRegistry` in `core.security`, which proves a
request came from an allowed Chrome extension installation, not from any particular person.
`UserAuthRegistry` proves the opposite: which account, if any, is signed in on this
installation. The two tokens travel in the same `Authorization: Bearer` header shape but are
never compared against each other, so a route can require one, the other, both or neither.

Tokens live in memory only, exactly like `SessionRegistry`'s do, and are lost when the
companion process restarts. That is an accepted limitation here too: the extension notices
its stored token no longer verifies and sends the user back to the login form rather than
silently losing their session mid-use.
"""

from __future__ import annotations

import secrets
import threading
import time

import bcrypt

# Long enough that a signed-in user is not asked to log in again every time the companion
# happens to still be running, short enough that a token copied out of extension storage
# does not stay valid forever.
AUTH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60

# bcrypt silently ignores any byte past 72, so a longer password would compare equal to a
# truncated one without this the request is rejected instead, at the schema layer.
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


class UserAuthRegistry:
    """Issues and verifies the bearer tokens login and signup hand back to the extension."""

    def __init__(self, ttl_seconds: int = AUTH_TOKEN_TTL_SECONDS):
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: str) -> str:
        """A fresh token bound to `user_id`, replacing none of that user's other sessions."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            self._tokens[token] = (user_id, time.monotonic() + self._ttl_seconds)
        return token

    def verify(self, token: str) -> str | None:
        """The user id `token` was issued to, refreshing its TTL, or None if it is not live."""
        with self._lock:
            self._prune_locked()
            record = self._tokens.get(token)
            if not record:
                return None
            user_id, _ = record
            self._tokens[token] = (user_id, time.monotonic() + self._ttl_seconds)
            return user_id

    def revoke(self, token: str) -> None:
        """Forget one token, for logout. Verifying it afterwards behaves as if it never existed."""
        with self._lock:
            self._tokens.pop(token, None)

    def _prune_locked(self) -> None:
        now = time.monotonic()
        expired = [token for token, (_, expiry) in self._tokens.items() if expiry <= now]
        for token in expired:
            self._tokens.pop(token, None)
