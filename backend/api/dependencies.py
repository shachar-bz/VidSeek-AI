"""Request-scoped access to the objects `create_app` built, and the auth gate.

The registry and job manager are held on `app.state` rather than in module globals so that
a test can build an app around its own instances, and so two apps in one process cannot
share state by accident.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager


def session_registry(request: Request) -> SessionRegistry:
    """The session registry this app was built with."""
    return request.app.state.session_registry


def job_manager(request: Request) -> JobManager:
    """The job manager this app was built with."""
    return request.app.state.job_manager


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
