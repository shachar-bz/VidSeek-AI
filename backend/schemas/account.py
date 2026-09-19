"""The account page's contract: the display name, the password, the sessions and the delete.

`schemas/auth.py` stays as it is -- it is what signing up and signing in exchange, and both
surfaces already speak it. This module is the account *management* half, which only the
website has: renaming yourself, changing a password you can still prove you know, seeing
where you are signed in, and deleting the account.

There is no password reset here, and no email verification, deliberately: the specification
lists both as out of scope and the deployment has no email infrastructure at all. A user who
forgets their password has it reset against the database by the account owner.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .auth import MAX_PASSWORD_LENGTH

MAX_DISPLAY_NAME_LENGTH = 128

# The floor `SignUpRequest` already applies, repeated here so that changing a password
# cannot quietly set one that signing up would have refused.
MIN_PASSWORD_LENGTH = 8


class Surface(str, Enum):
    """Which client a session was opened from. Matches `sessions_surface_known` in
    `migrations/0017_sessions.sql`."""

    WEBSITE = "website"
    EXTENSION = "extension"


class UpdateAccountRequest(BaseModel):
    """Change the display name. The email is not editable: it is the login."""

    display_name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME_LENGTH)


class ChangePasswordRequest(BaseModel):
    """Set a new password, proving the current one first.

    Proving the current one matters even though the request already carries a valid session
    token: a token left live on a shared machine should not be enough to lock its owner out
    of their own account.
    """

    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class SessionSummary(BaseModel):
    """One session signed into this account, as the account page lists it.

    The token is not carried in any form, not even hashed. The page identifies a session by
    `session_id` in order to revoke it, and `current` is what stops a user revoking the
    session they are reading the page through without meaning to.
    """

    session_id: str
    surface: Surface
    created_at: str
    last_used_at: str
    expires_at: str
    current: bool = False


class SessionList(BaseModel):
    """Every live session on this account, most recently used first."""

    sessions: list[SessionSummary] = Field(default_factory=list)


class DeleteAccountRequest(BaseModel):
    """Delete the account, proving the password first.

    This removes the user row, every library link, every conversation and every pinned
    answer. Shared video data -- the videos themselves, their transcripts, chapters,
    memories, embeddings and blobs -- is untouched and stays available to other accounts.
    The password is required because the action is irreversible and the confirmation dialog
    is the only other thing standing in front of it.
    """

    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
