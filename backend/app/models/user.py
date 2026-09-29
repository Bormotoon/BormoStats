"""User models."""

from __future__ import annotations

from datetime import datetime

from app.models.enums import ClickHouseIntEnum
from app.models.organization import OrgMemberRole
from pydantic import BaseModel, Field


class UserRole(ClickHouseIntEnum):
    admin = 1
    analyst = 2


class User(BaseModel):
    """User record as exposed by the API. The API key itself is never returned here."""

    user_id: str
    name: str
    email: str
    role: UserRole
    organization_id: str = "default"
    is_active: bool = True
    api_key_id: str = ""
    api_key_created_at: datetime | None = None
    api_key_expires_at: datetime | None = None
    api_key_revoked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserWithApiKey(User):
    """Returned once on create/rotate; the plaintext key is not stored server-side."""

    api_key: str


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    role: UserRole = UserRole.analyst
    org_role: OrgMemberRole = OrgMemberRole.viewer
    api_key_ttl_days: int | None = Field(default=None, ge=1, le=3650)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    role: UserRole | None = None
    organization_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Only the platform admin key may move users between organizations",
    )
    is_active: bool | None = None


class ApiKeyRotateRequest(BaseModel):
    ttl_days: int | None = Field(default=None, ge=1, le=3650)


class PrincipalInfo(BaseModel):
    principal_id: str
    organization_id: str
    role: str
    scopes: list[str]
    auth_method: str
    name: str = ""
    email: str = ""
    api_key_expires_at: datetime | None = None
