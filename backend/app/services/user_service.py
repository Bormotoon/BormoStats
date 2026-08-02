"""User management service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.models.user import User, UserCreate, UserRole, UserUpdate
from clickhouse_connect.driver import Client

_COLS = "user_id, name, email, api_key, role, organization_id, is_active, created_at, updated_at"
_INSERT = (
    "INSERT INTO dim_user ({cols})"
    " VALUES ({uid:String}, {name:String}, {email:String}, {key:String},"
    " {role:Int8}, {org_id:String}, {active:UInt8}, {created:DateTime}, {now:DateTime})"
)


class UserService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    def list_users(self) -> list[User]:
        rows = self._ch.query(f"SELECT {_COLS} FROM dim_user FINAL ORDER BY created_at")
        return [_row_to_user(r) for r in rows.named_results()]

    def get_user(self, user_id: str) -> User | None:
        rows = self._ch.query(
            f"SELECT {_COLS} FROM dim_user FINAL WHERE user_id = {{uid:String}}",
            parameters={"uid": user_id},
        )
        for r in rows.named_results():
            return _row_to_user(r)
        return None

    def get_user_by_api_key(self, api_key: str) -> User | None:
        rows = self._ch.query(
            f"SELECT {_COLS} FROM dim_user FINAL WHERE api_key = {{key:String}} AND is_active = 1",
            parameters={"key": api_key},
        )
        for r in rows.named_results():
            return _row_to_user(r)
        return None

    def create_user(self, data: UserCreate) -> User:
        now = datetime.utcnow()
        user_id = str(uuid.uuid4())[:8]
        api_key = uuid.uuid4().hex
        self._ch.command(
            _INSERT.format(cols=_COLS),
            parameters={
                "uid": user_id,
                "name": data.name,
                "email": data.email,
                "key": api_key,
                "role": data.role.value,
                "org_id": data.organization_id,
                "active": 1,
                "created": now,
                "now": now,
            },
        )
        return User(
            user_id=user_id,
            name=data.name,
            email=data.email,
            api_key=api_key,
            role=data.role,
            organization_id=data.organization_id,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    def update_user(self, user_id: str, data: UserUpdate) -> User | None:
        existing = self.get_user(user_id)
        if existing is None:
            return None
        now = datetime.utcnow()
        name = data.name if data.name is not None else existing.name
        email = data.email if data.email is not None else existing.email
        role = data.role if data.role is not None else existing.role
        active = data.is_active if data.is_active is not None else existing.is_active
        org_id = (
            data.organization_id if data.organization_id is not None else existing.organization_id
        )
        self._ch.command(
            _INSERT.format(cols=_COLS),
            parameters={
                "uid": user_id,
                "name": name,
                "email": email,
                "key": existing.api_key,
                "role": role.value,
                "org_id": org_id,
                "active": 1 if active else 0,
                "created": existing.created_at or now,
                "now": now,
            },
        )
        return User(
            user_id=user_id,
            name=name,
            email=email,
            api_key=existing.api_key,
            role=role,
            organization_id=org_id,
            is_active=active,
            created_at=existing.created_at or now,
            updated_at=now,
        )

    def rotate_api_key(self, user_id: str) -> str | None:
        existing = self.get_user(user_id)
        if existing is None:
            return None
        new_key = uuid.uuid4().hex
        now = datetime.utcnow()
        self._ch.command(
            _INSERT.format(cols=_COLS),
            parameters={
                "uid": user_id,
                "name": existing.name,
                "email": existing.email,
                "key": new_key,
                "role": existing.role.value,
                "org_id": existing.organization_id,
                "active": 1 if existing.is_active else 0,
                "created": existing.created_at or now,
                "now": now,
            },
        )
        return new_key

    def delete_user(self, user_id: str) -> bool:
        existing = self.get_user(user_id)
        if existing is None:
            return False
        now = datetime.utcnow()
        self._ch.command(
            _INSERT.format(cols=_COLS),
            parameters={
                "uid": user_id,
                "name": existing.name,
                "email": existing.email,
                "key": existing.api_key,
                "role": existing.role.value,
                "org_id": existing.organization_id,
                "active": 0,
                "created": existing.created_at or now,
                "now": now,
            },
        )
        return True


def _row_to_user(r: dict[str, Any]) -> User:
    return User(
        user_id=r["user_id"],
        name=r["name"],
        email=r["email"],
        api_key=r["api_key"],
        role=UserRole(r["role"]),
        organization_id=r.get("organization_id", "default"),
        is_active=bool(r["is_active"]),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )
