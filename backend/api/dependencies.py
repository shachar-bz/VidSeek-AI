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
from backend.storage.postgres import PostgresUsers, StoredUser


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
    registry: UserAuthRegistry = request.app.state.user_auth_registry
    token = authorization.removeprefix("Bearer ") if authorization else ""
    user_id = registry.verify(token) if token else None
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    user = store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return user


def authorize(
    request: Request,
    authorization: str | None = Header(default=None),
    origin: str | None = Header(default=None),
) -> None:
    """Require a live bearer token, and an Origin for anything that changes state."""
    registry: SessionRegistry = request.app.state.session_registry
    token = authorization.removeprefix("Bearer ") if authorization else ""
    # Reads may arrive without an Origin header; anything that starts, retries or
    # cancels work may not. The loopback middleware still gates every request.
    require_origin = request.method not in {"GET", "HEAD"}
    if not registry.verify(token, origin, require_origin=require_origin):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
