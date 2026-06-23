"""Collaboration — user management endpoints."""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_api_key
from app.models.user import User, UserCreate, UserUpdate
from app.services.user_service import UserService
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/users", tags=["users"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> UserService:
    return UserService(ch)


@router.get("")
def list_users(
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> list[User]:
    """List all users (admin only)."""
    return _svc(ch).list_users()


@router.get("/{user_id}")
def get_user(
    user_id: str,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> User:
    """Get user by ID (admin only)."""
    user = _svc(ch).get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> User:
    """Create a new user with generated API key (admin only)."""
    return _svc(ch).create_user(body)


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    body: UserUpdate,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> User:
    """Update user details (admin only)."""
    user = _svc(ch).update_user(user_id, body)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.post("/{user_id}/rotate-key")
def rotate_key(
    user_id: str,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> dict[str, str]:
    """Rotate user's API key (admin only)."""
    key = _svc(ch).rotate_api_key(user_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"api_key": key}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> dict[str, bool]:
    """Deactivate user (admin only)."""
    ok = _svc(ch).delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"deleted": True}
