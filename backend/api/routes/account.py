"""Authenticated account profile, password, and deletion HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.dependencies import current_user, sessions_store, users_store
from backend.core.auth import hash_password, verify_password
from backend.schemas.account import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    UpdateAccountRequest,
)
from backend.schemas.auth import UserResponse
from backend.storage.postgres import PostgresSessions, PostgresUsers, StoredUser

router = APIRouter(prefix="/v1/account")


def _response(user: StoredUser) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)


@router.patch("", response_model=UserResponse)
def update_account(
    payload: UpdateAccountRequest,
    user: StoredUser = Depends(current_user),
    store: PostgresUsers = Depends(users_store),
) -> UserResponse:
    updated = store.update_display_name(user.id, payload.display_name)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return _response(updated)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    user: StoredUser = Depends(current_user),
    store: PostgresUsers = Depends(users_store),
    sessions: PostgresSessions = Depends(sessions_store),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        )
    if not store.update_password_hash(user.id, hash_password(payload.new_password)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    sessions.revoke_all(user.id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    payload: DeleteAccountRequest,
    user: StoredUser = Depends(current_user),
    store: PostgresUsers = Depends(users_store),
) -> None:
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Password is incorrect"
        )
    if not store.delete(user.id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
