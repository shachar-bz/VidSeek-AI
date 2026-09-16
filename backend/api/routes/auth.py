"""Signup, login, account lookup and logout for a VidSeek user account.

Every route here still runs behind the loopback middleware and the CORS allowlist in
`api.app`, and signup/login additionally check `Origin` themselves, the same way
`/v1/session` does: unlike the video job routes there is no bearer token yet to gate these
on, so the Chrome extension origin is the only thing standing between them and any other
local process that can reach this port.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from backend.api.dependencies import (
    current_user,
    session_registry,
    user_auth_registry,
    users_store,
)
from backend.core.auth import UserAuthRegistry, hash_password, normalize_email, verify_password
from backend.core.errors import EmailAlreadyRegisteredError
from backend.core.security import SessionRegistry
from backend.schemas.auth import AuthResponse, LoginRequest, SignUpRequest, UserResponse
from backend.storage.postgres import NewUser, PostgresUsers, StoredUser, is_postgres_configured

router = APIRouter(prefix="/v1/auth")

ACCOUNTS_UNAVAILABLE = "Accounts require a configured database"
INVALID_CREDENTIALS = "Invalid email or password"


def _require_extension_origin(origin: str | None, registry: SessionRegistry) -> None:
    if not registry.is_allowed_origin(origin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Extension origin is not allowed; configure VIDSEEK_EXTENSION_IDS",
        )


def _require_postgres() -> None:
    if not is_postgres_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ACCOUNTS_UNAVAILABLE
        )


def _as_response(user: StoredUser) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)


@router.post("/signup", response_model=AuthResponse)
def signup(
    payload: SignUpRequest,
    origin: str | None = Header(default=None),
    registry: SessionRegistry = Depends(session_registry),
    auth_registry: UserAuthRegistry = Depends(user_auth_registry),
    store: PostgresUsers = Depends(users_store),
) -> AuthResponse:
    _require_extension_origin(origin, registry)
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
    token = auth_registry.issue(stored.id)
    return AuthResponse(token=token, user=_as_response(stored))


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    origin: str | None = Header(default=None),
    registry: SessionRegistry = Depends(session_registry),
    auth_registry: UserAuthRegistry = Depends(user_auth_registry),
    store: PostgresUsers = Depends(users_store),
) -> AuthResponse:
    _require_extension_origin(origin, registry)
    _require_postgres()
    stored = store.get_by_email(normalize_email(payload.email))
    if not stored or not verify_password(payload.password, stored.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)
    token = auth_registry.issue(stored.id)
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
