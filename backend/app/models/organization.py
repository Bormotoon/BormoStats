from __future__ import annotations

from datetime import datetime
from enum import IntEnum

from pydantic import BaseModel, Field


class OrgMemberRole(IntEnum):
    owner = 1
    admin = 2
    manager = 3
    analyst = 4
    viewer = 5


class Organization(BaseModel):
    organization_id: str
    name: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)


class OrganizationMember(BaseModel):
    organization_id: str
    user_id: str
    role: OrgMemberRole
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrganizationMemberCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    role: OrgMemberRole = OrgMemberRole.viewer


class OrganizationMemberUpdate(BaseModel):
    role: OrgMemberRole


class ShopAccount(BaseModel):
    account_id: str
    marketplace: str
    organization_id: str
    title: str
    is_active: bool = True
    created_at: datetime | None = None


class ShopAccountCreate(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)
    marketplace: str = Field(min_length=2, max_length=10, pattern=r"^(wb|ozon)$")
    title: str = Field(min_length=1, max_length=255)
    is_active: bool = True


class ShopAccountUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
