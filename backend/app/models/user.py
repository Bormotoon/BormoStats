"""User models."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum

from pydantic import BaseModel, Field


class UserRole(IntEnum):
    admin = 1
    analyst = 2


class User(BaseModel):
    user_id: str
    name: str
    email: str
    api_key: str
    role: UserRole
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    role: UserRole = UserRole.analyst


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    role: UserRole | None = None
    is_active: bool | None = None
