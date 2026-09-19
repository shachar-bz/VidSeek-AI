"""Signup, login, account lookup, logout and session management for a VidSeek user account.

Every route here still runs behind the loopback middleware and the CORS allowlist in
`api.app`, and signup/login additionally check `Origin` themselves, the same way
`/v1/session` does: unlike the video job routes there is no bearer token yet to gate these
on, so the calling origin is the only thing standing between them and any other local process
or web page that can reach this port. That same origin is also what decides `surface` --
never a label the client sends -- so a session's `sessions.surface` column can be trusted by
the account page.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status

from backend.api.dependencies import (
    current_session,
    current_user,
    session_registry,
    sessions_store,
    user_auth_registry,
    users_store,
)
from backend.core import config
from backend.core.auth import UserAuthRegistry, hash_password, normalize_email, verify_password
from backend.core.errors import EmailAlreadyRegisteredError
from backend.core.security import SessionRegistry
from backend.schemas.account import SessionList, SessionSummary, Surface
from backend.schemas.auth import AuthResponse, LoginRequest, SignUpRequest, UserResponse
from backend.storage.postgres import (
    NewUser,
    PostgresSessions,
    PostgresUsers,
    StoredSession,
    StoredUser,
    is_postgres_configured,
)

router = APIRouter(prefix="/v1/auth")

ACCOUNTS_UNAVAILABLE = "Accounts require a configured database"
INVALID_CREDENTIALS = "Invalid email or password"
ORIGIN_NOT_ALLOWED = (
    "Origin is not allowed; configure VIDSEEK_EXTENSION_IDS or VIDSEEK_WEBSITE_ORIGINS"
)


def _determine_surface(origin: str | None, registry: SessionRegistry) -> Surface | None:
    """Which surface `origin` belongs to, decided here rather than trusted from the client.

    An allowed Chrome extension origin is `extension`; a configured VidSeek website origin
    is `website`. Anything else -- including a client that simply claims to be one or the
    other -- is neither.
    """
    if registry.is_allowed_origin(origin):
        return Surface.EXTENSION
    if origin and origin in config.website_origins():
        return Surface.WEBSITE
    return None


def _require_surface(origin: str | None, registry: SessionRegistry) -> Surface:
    surface = _determine_surface(origin, registry)
    if surface is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ORIGIN_NOT_ALLOWED)
    return surface


def _require_postgres() -> None:
    if not is_postgres_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ACCOUNTS_UNAVAILABLE
        )


def _as_response(user: StoredUser) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)


def _as_summary(session: StoredSession, *, current: bool) -> SessionSummary:
    return SessionSummary(
        session_id=session.id,
        surface=Surface(session.surface),
        created_at=session.created_at,
        last_used_at=session.last_used_at,
        expires_at=session.expires_at,
        current=current,
    )


@router.post("/signup", response_model=AuthResponse)
def signup(
    payload: SignUpRequest,
    origin: str | None = Header(default=None),
    registry: SessionRegistry = Depends(session_registry),
    auth_registry: UserAuthRegistry = Depends(user_auth_registry),
    store: PostgresUsers = Depends(users_store),
) -> AuthResponse:
    surface = _require_surface(origin, registry)
    _require_postgres()
    try:
        stored = store.create(
            NewUser(
                email=normalize_email(payload.email),
                password_hash=hash_password(payload.password),
                display_name=payload.display_name,
            )
        )
    except EmailAlreadyRegisteredError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    token = auth_registry.issue(stored.id, surface.value)
    return AuthResponse(token=token, user=_as_response(stored))


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    origin: str | None = Header(default=None),
    registry: SessionRegistry = Depends(session_registry),
    auth_registry: UserAuthRegistry = Depends(user_auth_registry),
    store: PostgresUsers = Depends(users_store),
) -> AuthResponse:
    surface = _require_surface(origin, registry)
    _require_postgres()
    stored = store.get_by_email(normalize_email(payload.email))
    if not stored or not verify_password(payload.password, stored.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)
    token = auth_registry.issue(stored.id, surface.value)
    return AuthResponse(token=token, user=_as_response(stored))


@router.get("/me", response_model=UserResponse)
def me(user: StoredUser = Depends(current_user)) -> UserResponse:
    return _as_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    authorization: str | None = Header(default=None),
    auth_registry: UserAuthRegistry = Depends(user_auth_registry),
) -> None:
    token = authorization.removeprefix("Bearer ") if authorization else ""
    if token:
        auth_registry.revoke(token)


@router.get("/sessions", response_model=SessionList)
def list_sessions(
    session: StoredSession = Depends(current_session),
    store: PostgresSessions = Depends(sessions_store),
) -> SessionList:
    found = store.list_for_user(session.user_id)
    return SessionList(
        sessions=[_as_summary(item, current=item.id == session.id) for item in found]
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    session_id: str,
    session: StoredSession = Depends(current_session),
    store: PostgresSessions = Depends(sessions_store),
) -> None:
    try:
        uuid.UUID(session_id)
    except ValueError:
        # Not a real session id, so there is nothing of this user's to revoke -- the same
        # outcome as a well-formed id that does not belong to them.
        return
    store.revoke(session.user_id, session_id)


@router.post("/sessions/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
def revoke_all_sessions(
    session: StoredSession = Depends(current_session),
    store: PostgresSessions = Depends(sessions_store),
) -> None:
    store.revoke_all(session.user_id)
