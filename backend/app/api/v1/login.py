"""Sign-in with e-mail and password for the web UI; API keys stay for scripts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import (
    ApiKeyHeader,
    AuthContextDependency,
    AuthMethod,
    UserAdminAuth,
    invalidate_auth_cache,
)
from app.core.deps import ChClientDependency
from app.services.session_service import MIN_PASSWORD_LENGTH, SessionService
from app.services.user_service import UserService
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["auth"], responses=API_ERROR_RESPONSES)

PasswordField = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    name: str
    email: str


class PasswordChange(BaseModel):
    current_password: str = Field(default="", max_length=256)
    new_password: PasswordField


class PasswordSet(BaseModel):
    password: PasswordField


@router.post("/login")
def login(body: LoginRequest, ch: ChClientDependency) -> LoginResponse:
    """Open a 30-day session; the token goes into ``X-API-Key`` like an API key."""
    service = SessionService(ch)
    user_id = service.verify_login(body.email, body.password)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong e-mail or password"
        )
    user = UserService(ch).get_user(user_id, None)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    session = service.create_session(user_id)
    return LoginResponse(
        token=session.token, expires_at=session.expires_at, name=user.name, email=user.email
    )


@router.post("/logout")
def logout(
    auth: AuthContextDependency, ch: ChClientDependency, x_api_key: ApiKeyHeader = ""
) -> dict[str, bool]:
    """End the current session on the server (API keys are revoked under /users)."""
    revoked = False
    if auth.auth_method == AuthMethod.session:
        revoked = SessionService(ch).revoke(x_api_key)
        invalidate_auth_cache()
    return {"revoked": revoked}


@router.post("/password")
def change_password(
    body: PasswordChange, auth: AuthContextDependency, ch: ChClientDependency
) -> dict[str, bool]:
    """Change the caller's own password (the current one is required once it is set)."""
    if auth.auth_method not in (AuthMethod.session, AuthMethod.user_key):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="not a user")
    service = SessionService(ch)
    stored = ch.query(
        "SELECT count() FROM dim_user_credential FINAL WHERE user_id = {uid:String}",
        parameters={"uid": auth.principal_id},
    ).result_rows[0][0]
    if stored and not service.check_password(auth.principal_id, body.current_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="current password is wrong"
        )
    service.set_password(auth.principal_id, body.new_password)
    return {"changed": True}


@router.put("/users/{user_id}/password")
def set_user_password(
    user_id: str, body: PasswordSet, auth: UserAdminAuth, ch: ChClientDependency
) -> dict[str, bool]:
    """An owner/admin (or the platform key) sets a user's password."""
    if UserService(ch).get_user(user_id, auth.platform_organization_filter) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    SessionService(ch).set_password(user_id, body.password)
    return {"changed": True}
