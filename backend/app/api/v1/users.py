from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import (
    ChClientDependency,
    CurrentUserDependency,
    require_admin_key_or_org_role,
)
from app.models.organization import OrgMemberRole
from app.models.user import User, UserCreate, UserUpdate
from app.services.user_service import UserService
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/users", tags=["users"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> UserService:
    return UserService(ch)


@router.get("/me")
def get_current_user_info(
    current_user: CurrentUserDependency,
) -> User:
    return current_user


@router.get("")
def list_users(
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> list[User]:
    return _svc(ch).list_users()


@router.get("/{user_id}")
def get_user(
    user_id: str,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> User:
    user = _svc(ch).get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> User:
    return _svc(ch).create_user(body)


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    body: UserUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> User:
    user = _svc(ch).update_user(user_id, body)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.post("/{user_id}/rotate-key")
def rotate_key(
    user_id: str,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> dict[str, str]:
    key = _svc(ch).rotate_api_key(user_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"api_key": key}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> dict[str, bool]:
    ok = _svc(ch).delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"deleted": True}
