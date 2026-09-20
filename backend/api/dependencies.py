"""Request-scoped access to the objects `create_app` built, and the auth gate.

The registry and job manager are held on `app.state` rather than in module globals so that
a test can build an app around its own instances, and so two apps in one process cannot
share state by accident.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from backend.core.auth import UserAuthRegistry
from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager
from backend.storage.postgres import PostgresSessions, PostgresUsers, StoredSession, StoredUser


def session_registry(request: Request) -> SessionRegistry:
    """The session registry this app was built with."""
    return request.app.state.session_registry


def job_manager(request: Request) -> JobManager:
    """The job manager this app was built with."""
    return request.app.state.job_manager


def user_auth_registry(request: Request) -> UserAuthRegistry:
    """The user auth token registry this app was built with."""
    return request.app.state.user_auth_registry


def users_store(request: Request) -> PostgresUsers:
    """The `users` table store this app was built with."""
    return request.app.state.users_store


def sessions_store(request: Request) -> PostgresSessions:
    """The `sessions` table store this app was built with."""
    return request.app.state.sessions_store


def _authenticated_session(token: str | None, request: Request) -> StoredSession:
    registry: UserAuthRegistry = request.app.state.user_auth_registry
    session = registry.verify(token) if token else None
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return session


def _signed_in_user(token: str | None, request: Request, store: PostgresUsers) -> StoredUser:
    session = _authenticated_session(token, request)
    user = store.get_by_id(session.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return user


def current_session(
    request: Request,
    authorization: str | None = Header(default=None),
) -> StoredSession:
    """The durable session record the request's bearer token names.

    Separate from `current_user` below because a route only needs this one when it has to
    tell the session that authenticated it apart from the account's other sessions -- listing
    them, for instance, needs to mark which one is `current`.
    """
    token = authorization.removeprefix("Bearer ") if authorization else ""
    return _authenticated_session(token or None, request)


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    store: PostgresUsers = Depends(users_store),
) -> StoredUser:
    """The signed-in account a login/signup token names.

    A separate gate from `authorize` below: that one proves the request came from the
    allowed Chrome extension, this one proves which account, if any, is using it. Both read
    the same `Authorization` header shape, but against independent registries, so a route
    that needs one never has to also satisfy the other.
    """
    token = authorization.removeprefix("Bearer ") if authorization else ""
    return _signed_in_user(token or None, request, store)


def current_user_for_job_creation(
    request: Request,
    x_vidseek_user_token: str | None = Header(default=None),
    store: PostgresUsers = Depends(users_store),
) -> StoredUser:
    """The account starting a video job, so the video it produces can be recorded as theirs.

    Job creation already spends `Authorization` on `authorize`'s extension-session bearer,
    so the account token travels in this header of its own rather than contending with it.
    """
    return _signed_in_user(x_vidseek_user_token, request, store)


def authorize(
    request: Request,
    authorization: str | None = Header(default=None),
    origin: str | None = Header(default=None),
) -> None:
    """Require a live bearer token, and an Origin for anything that changes state."""
    registry: SessionRegistry = request.app.state.session_registry
    token = authorization.removeprefix("Bearer ") if authorization else ""
    # Reads may arrive without an Origin header; anything that starts, retries or
    # cancels work may not. Local deployments also retain the loopback gate; hosted
    # deployments rely on their network boundary while keeping this extension check.
    require_origin = request.method not in {"GET", "HEAD"}
    if not registry.verify(token, origin, require_origin=require_origin):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
