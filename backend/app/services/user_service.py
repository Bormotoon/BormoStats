"""User management service.

User API keys are stored as ``api_key_id`` + salted hash; the plaintext key is
returned only by :meth:`UserService.create_user` and :meth:`UserService.rotate_api_key`.
Every method takes the caller's ``organization_id`` (``None`` means platform-wide
access for the master admin key) so tenants never see each other's users.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.security import IssuedApiKey, generate_api_key
from app.db.ch import insert_values_sql, utc_now
from app.models.organization import OrgMemberRole
from app.models.user import User, UserCreate, UserRole, UserUpdate, UserWithApiKey
from clickhouse_connect.driver import Client

_SELECT_COLS = (
    "user_id, name, email, role, organization_id, is_active, api_key_id, api_key_hash,"
    " api_key_created_at, api_key_expires_at, api_key_revoked_at, created_at, updated_at"
)
_USER_INSERT = insert_values_sql(
    "dim_user",
    (
        ("user_id", "String"),
        ("name", "String"),
        ("email", "String"),
        ("api_key", "String"),
        ("role", "String"),
        ("organization_id", "String"),
        ("is_active", "UInt8"),
        ("api_key_id", "String"),
        ("api_key_hash", "String"),
        ("api_key_created_at", "Nullable(DateTime)"),
        ("api_key_expires_at", "Nullable(DateTime)"),
        ("api_key_revoked_at", "Nullable(DateTime)"),
        ("created_at", "DateTime"),
        ("updated_at", "DateTime"),
    ),
)
_MEMBER_INSERT = insert_values_sql(
    "dim_organization_member",
    (
        ("organization_id", "String"),
        ("user_id", "String"),
        ("role", "String"),
        ("created_at", "DateTime"),
        ("updated_at", "DateTime"),
    ),
)


@dataclass(frozen=True)
class StoredUser:
    """Internal view of a user row, including the key hash used for verification."""

    user: User
    api_key_hash: str


class UserService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    # -- Queries --------------------------------------------------------------------

    def list_users(self, organization_id: str | None) -> list[User]:
        where, params = _org_filter(organization_id)
        rows = self._ch.query(
            f"SELECT {_SELECT_COLS} FROM dim_user FINAL{where} ORDER BY created_at",
            parameters=params,
        )
        return [_row_to_stored(r).user for r in rows.named_results()]

    def get_user(self, user_id: str, organization_id: str | None) -> User | None:
        stored = self._get_stored(user_id, organization_id)
        return stored.user if stored else None

    def find_by_key_id(self, key_id: str) -> StoredUser | None:
        rows = self._ch.query(
            f"SELECT {_SELECT_COLS} FROM dim_user FINAL"
            " WHERE api_key_id = {kid:String} AND is_active = 1 LIMIT 1",
            parameters={"kid": key_id},
        )
        for r in rows.named_results():
            return _row_to_stored(r)
        return None

    def get_member_role(self, organization_id: str, user_id: str) -> OrgMemberRole | None:
        rows = self._ch.query(
            "SELECT role FROM dim_organization_member FINAL"
            " WHERE organization_id = {oid:String} AND user_id = {uid:String} LIMIT 1",
            parameters={"oid": organization_id, "uid": user_id},
        )
        for r in rows.named_results():
            return OrgMemberRole.parse(r["role"])
        return None

    # -- Mutations ------------------------------------------------------------------

    def create_user(self, data: UserCreate, organization_id: str) -> UserWithApiKey:
        now = utc_now()
        issued = generate_api_key()
        user = User(
            user_id=_new_id(),
            name=data.name,
            email=data.email,
            role=data.role,
            organization_id=organization_id,
            is_active=True,
            api_key_id=issued.key_id,
            api_key_created_at=now,
            api_key_expires_at=_expiry(now, data.api_key_ttl_days),
            created_at=now,
            updated_at=now,
        )
        self._write(user, issued.key_hash)
        self._ch.command(
            _MEMBER_INSERT,
            parameters={
                "organization_id": organization_id,
                "user_id": user.user_id,
                "role": data.org_role.name,
                "created_at": now,
                "updated_at": now,
            },
        )
        return UserWithApiKey(**user.model_dump(), api_key=issued.plaintext)

    def update_user(
        self,
        user_id: str,
        data: UserUpdate,
        organization_id: str | None,
    ) -> User | None:
        stored = self._get_stored(user_id, organization_id)
        if stored is None:
            return None
        existing = stored.user
        updated = existing.model_copy(
            update={
                "name": data.name if data.name is not None else existing.name,
                "email": data.email if data.email is not None else existing.email,
                "role": data.role if data.role is not None else existing.role,
                "organization_id": data.organization_id or existing.organization_id,
                "is_active": data.is_active if data.is_active is not None else existing.is_active,
                "updated_at": utc_now(),
            }
        )
        self._write(updated, stored.api_key_hash)
        return updated

    def rotate_api_key(
        self,
        user_id: str,
        organization_id: str | None,
        ttl_days: int | None = None,
    ) -> UserWithApiKey | None:
        stored = self._get_stored(user_id, organization_id)
        if stored is None:
            return None
        now = utc_now()
        issued: IssuedApiKey = generate_api_key()
        updated = stored.user.model_copy(
            update={
                "api_key_id": issued.key_id,
                "api_key_created_at": now,
                "api_key_expires_at": _expiry(now, ttl_days),
                "api_key_revoked_at": None,
                "updated_at": now,
            }
        )
        self._write(updated, issued.key_hash)
        return UserWithApiKey(**updated.model_dump(), api_key=issued.plaintext)

    def revoke_api_key(self, user_id: str, organization_id: str | None) -> bool:
        stored = self._get_stored(user_id, organization_id)
        if stored is None:
            return False
        self._revoke(stored)
        return True

    def revoke_all_api_keys(self, organization_id: str | None) -> int:
        where, params = _org_filter(organization_id)
        rows = self._ch.query(
            f"SELECT {_SELECT_COLS} FROM dim_user FINAL{where}",
            parameters=params,
        )
        count = 0
        for r in rows.named_results():
            stored = _row_to_stored(r)
            if stored.user.api_key_id and stored.user.api_key_revoked_at is None:
                self._revoke(stored)
                count += 1
        return count

    def upgrade_key_hash(self, stored: StoredUser, new_hash: str) -> None:
        """Replace a legacy digest with a salted scrypt hash after successful auth."""
        self._write(stored.user.model_copy(update={"updated_at": utc_now()}), new_hash)

    def delete_user(self, user_id: str, organization_id: str | None) -> bool:
        stored = self._get_stored(user_id, organization_id)
        if stored is None:
            return False
        now = utc_now()
        deactivated = stored.user.model_copy(
            update={"is_active": False, "api_key_revoked_at": now, "updated_at": now}
        )
        self._write(deactivated, "")
        return True

    # -- Helpers --------------------------------------------------------------------

    def _get_stored(self, user_id: str, organization_id: str | None) -> StoredUser | None:
        where, params = _org_filter(organization_id)
        clause = (
            f"{where} AND user_id = {{uid:String}}" if where else " WHERE user_id = {uid:String}"
        )
        rows = self._ch.query(
            f"SELECT {_SELECT_COLS} FROM dim_user FINAL{clause} LIMIT 1",
            parameters={**params, "uid": user_id},
        )
        for r in rows.named_results():
            return _row_to_stored(r)
        return None

    def _revoke(self, stored: StoredUser) -> None:
        now = utc_now()
        self._write(
            stored.user.model_copy(update={"api_key_revoked_at": now, "updated_at": now}),
            "",
        )

    def _write(self, user: User, api_key_hash: str) -> None:
        self._ch.command(
            _USER_INSERT,
            parameters={
                "user_id": user.user_id,
                "name": user.name,
                "email": user.email,
                "api_key": "",
                "role": user.role.name,
                "organization_id": user.organization_id,
                "is_active": 1 if user.is_active else 0,
                "api_key_id": user.api_key_id,
                "api_key_hash": api_key_hash,
                "api_key_created_at": user.api_key_created_at,
                "api_key_expires_at": user.api_key_expires_at,
                "api_key_revoked_at": user.api_key_revoked_at,
                "created_at": user.created_at or utc_now(),
                "updated_at": user.updated_at or utc_now(),
            },
        )


def _new_id() -> str:
    return str(uuid.uuid4())


def _expiry(now: datetime, ttl_days: int | None) -> datetime | None:
    return now + timedelta(days=ttl_days) if ttl_days else None


def _org_filter(organization_id: str | None) -> tuple[str, dict[str, object]]:
    if organization_id is None:
        return "", {}
    return " WHERE organization_id = {oid:String}", {"oid": organization_id}


def _row_to_stored(r: dict[str, Any]) -> StoredUser:
    user = User(
        user_id=r["user_id"],
        name=r["name"],
        email=r["email"],
        role=UserRole.parse(r["role"]),
        organization_id=r.get("organization_id") or "default",
        is_active=bool(r["is_active"]),
        api_key_id=r.get("api_key_id") or "",
        api_key_created_at=r.get("api_key_created_at"),
        api_key_expires_at=r.get("api_key_expires_at"),
        api_key_revoked_at=r.get("api_key_revoked_at"),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )
    return StoredUser(user=user, api_key_hash=r.get("api_key_hash") or "")
