"""The signup, login and account-info contract shared with the Chrome extension.

`UserResponse` is deliberately hash-free: the extension only ever needs to know who is
signed in, never anything it could use to re-derive or replay a credential.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

# bcrypt silently ignores any byte past 72; rejecting a longer password here is what keeps
# that limit from being invisible to whoever is typing one in.
MAX_PASSWORD_LENGTH = 72


class SignUpRequest(BaseModel):
    """A new account: an email, a password, and an optional name to display."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_LENGTH)
    display_name: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    """Credentials for an existing account."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    """One account, as the extension is allowed to see it."""

    id: str
    email: str
    display_name: str | None = None


class AuthResponse(BaseModel):
    """What signup and login both hand back: a bearer token and the account it belongs to."""

    token: str
    user: UserResponse
