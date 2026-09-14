"""Issues the short-lived bearer token every other route requires."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from backend.api.dependencies import session_registry
from backend.core.security import SessionRegistry

router = APIRouter()


@router.post("/v1/session")
def create_session(
    origin: str | None = Header(default=None),
    registry: SessionRegistry = Depends(session_registry),
) -> dict[str, object]:
    try:
        token = registry.create(origin)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return {"token": token, "expires_in_seconds": 1800}
