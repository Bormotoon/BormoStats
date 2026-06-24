"""User models."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum

from pydantic import BaseModel, Field


class UserRole(IntEnum):
    admin = 1
    analyst = 2


class OrgUserRole(IntEnum):
    owner = 1
    admin = 2
    manager = 3
    analyst = 4
    viewer = 5


class User(BaseModel):
    user_id: str
    name: str
    email: str
    api_key: str
    role: UserRole
    organization_id: str = "default"
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    role: UserRole = UserRole.analyst
    organization_id: str = Field(default="default", min_length=1, max_length=64)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    role: UserRole | None = None
    organization_id: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None
