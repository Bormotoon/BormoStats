from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import (
    AuthContextDependency,
    UserAdminAuth,
    invalidate_auth_cache,
    role_allows,
)
from app.core.deps import ChClientDependency
from app.models.user import (
    ApiKeyRotateRequest,
    PrincipalInfo,
    User,
    UserCreate,
    UserUpdate,
    UserWithApiKey,
)
from app.services.user_service import UserService
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/users", tags=["users"], responses=API_ERROR_RESPONSES)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")


@router.get("/me")
def get_current_principal(auth: AuthContextDependency) -> PrincipalInfo:
    return PrincipalInfo(
        principal_id=auth.principal_id,
        organization_id=auth.organization_id,
        role=auth.role.name,
        scopes=sorted(str(scope) for scope in auth.scopes),
        auth_method=str(auth.auth_method),
        name=auth.name,
        email=auth.email,
        api_key_expires_at=auth.api_key_expires_at,
    )


@router.get("")
def list_users(ch: ChClientDependency, auth: UserAdminAuth) -> list[User]:
    return UserService(ch).list_users(auth.platform_organization_filter)


@router.get("/{user_id}")
def get_user(user_id: str, ch: ChClientDependency, auth: UserAdminAuth) -> User:
    user = UserService(ch).get_user(user_id, auth.platform_organization_filter)
    if user is None:
        raise _not_found()
    return user


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, ch: ChClientDependency, auth: UserAdminAuth) -> UserWithApiKey:
    """Create a user in the caller's organization; the API key is returned only once."""
    if not role_allows(auth.role, body.org_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot grant a role above your own",
        )
    return UserService(ch).create_user(body, auth.organization_id)


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    body: UserUpdate,
    ch: ChClientDependency,
    auth: UserAdminAuth,
) -> User:
    if body.organization_id is not None and not auth.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the platform admin may move users between organizations",
        )
    user = UserService(ch).update_user(user_id, body, auth.platform_organization_filter)
    if user is None:
        raise _not_found()
    invalidate_auth_cache()
    return user


@router.post("/{user_id}/rotate-key")
def rotate_key(
    user_id: str,
    ch: ChClientDependency,
    auth: UserAdminAuth,
    body: ApiKeyRotateRequest | None = None,
) -> UserWithApiKey:
    ttl_days = body.ttl_days if body else None
    user = UserService(ch).rotate_api_key(user_id, auth.platform_organization_filter, ttl_days)
    if user is None:
        raise _not_found()
    invalidate_auth_cache()
    return user


@router.post("/{user_id}/revoke-key")
def revoke_key(user_id: str, ch: ChClientDependency, auth: UserAdminAuth) -> dict[str, bool]:
    if not UserService(ch).revoke_api_key(user_id, auth.platform_organization_filter):
        raise _not_found()
    invalidate_auth_cache()
    return {"revoked": True}


@router.post("/revoke-all-keys")
def revoke_all_keys(ch: ChClientDependency, auth: UserAdminAuth) -> dict[str, int]:
    """Emergency switch: revoke every user key in the caller's organization.

    Even the platform admin revokes one organization (``X-Organization-Id``) at a time.
    """
    revoked = UserService(ch).revoke_all_api_keys(auth.organization_id)
    invalidate_auth_cache()
    return {"revoked": revoked}


@router.delete("/{user_id}")
def delete_user(user_id: str, ch: ChClientDependency, auth: UserAdminAuth) -> dict[str, bool]:
    if user_id == auth.principal_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cannot delete yourself")
    if not UserService(ch).delete_user(user_id, auth.platform_organization_filter):
        raise _not_found()
    invalidate_auth_cache()
    return {"deleted": True}
