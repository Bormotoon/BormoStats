from __future__ import annotations

import uuid
from typing import Any

from app.db.ch import insert_values_sql, utc_now
from app.models.organization import (
    Organization,
    OrganizationCreate,
    OrganizationMember,
    OrganizationMemberCreate,
    OrganizationMemberUpdate,
    OrganizationUpdate,
    OrgMemberRole,
    ShopAccount,
    ShopAccountCreate,
    ShopAccountUpdate,
)
from clickhouse_connect.driver import Client

_ORG_COLUMNS: tuple[tuple[str, str], ...] = (
    ("organization_id", "String"),
    ("name", "String"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_MEMBER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("organization_id", "String"),
    ("user_id", "String"),
    ("role", "String"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_ACCT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("account_id", "String"),
    ("marketplace", "String"),
    ("organization_id", "String"),
    ("title", "String"),
    ("created_at", "DateTime"),
)
_ORG_COLS = ", ".join(name for name, _ in _ORG_COLUMNS)
_MEMBER_COLS = ", ".join(name for name, _ in _MEMBER_COLUMNS)
_ACCT_COLS = ", ".join(name for name, _ in _ACCT_COLUMNS)
_ORG_INSERT = insert_values_sql("dim_organization", _ORG_COLUMNS)
_MEMBER_INSERT = insert_values_sql("dim_organization_member", _MEMBER_COLUMNS)
_ACCT_INSERT = insert_values_sql("dim_account", _ACCT_COLUMNS)


class OrganizationService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    def list_organizations(self) -> list[Organization]:
        rows = self._ch.query(f"SELECT {_ORG_COLS} FROM dim_organization FINAL ORDER BY created_at")
        return [_row_to_org(r) for r in rows.named_results()]

    def get_organization(self, organization_id: str) -> Organization | None:
        rows = self._ch.query(
            f"SELECT {_ORG_COLS} FROM dim_organization FINAL"
            " WHERE organization_id = {oid:String}",
            parameters={"oid": organization_id},
        )
        for r in rows.named_results():
            return _row_to_org(r)
        return None

    def create_organization(self, data: OrganizationCreate) -> Organization:
        now = utc_now()
        org_id = str(uuid.uuid4())
        self._ch.command(
            _ORG_INSERT,
            parameters={
                "organization_id": org_id,
                "name": data.name,
                "created_at": now,
                "updated_at": now,
            },
        )
        return Organization(
            organization_id=org_id,
            name=data.name,
            created_at=now,
            updated_at=now,
        )

    def update_organization(
        self, organization_id: str, data: OrganizationUpdate
    ) -> Organization | None:
        existing = self.get_organization(organization_id)
        if existing is None:
            return None
        now = utc_now()
        name = data.name if data.name is not None else existing.name
        self._ch.command(
            _ORG_INSERT,
            parameters={
                "organization_id": organization_id,
                "name": name,
                "created_at": existing.created_at or now,
                "updated_at": now,
            },
        )
        return Organization(
            organization_id=organization_id,
            name=name,
            created_at=existing.created_at or now,
            updated_at=now,
        )

    def delete_organization(self, organization_id: str) -> bool:
        existing = self.get_organization(organization_id)
        if existing is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_organization DELETE WHERE organization_id = {oid:String}",
            parameters={"oid": organization_id},
        )
        self._ch.command(
            "ALTER TABLE dim_organization_member DELETE WHERE organization_id = {oid:String}",
            parameters={"oid": organization_id},
        )
        return True

    # Members
    def list_members(self, organization_id: str) -> list[OrganizationMember]:
        rows = self._ch.query(
            f"SELECT {_MEMBER_COLS} FROM dim_organization_member FINAL"
            " WHERE organization_id = {oid:String} ORDER BY created_at",
            parameters={"oid": organization_id},
        )
        return [_row_to_member(r) for r in rows.named_results()]

    def add_member(
        self, organization_id: str, data: OrganizationMemberCreate
    ) -> OrganizationMember:
        now = utc_now()
        self._ch.command(
            _MEMBER_INSERT,
            parameters={
                "organization_id": organization_id,
                "user_id": data.user_id,
                "role": data.role.name,
                "created_at": now,
                "updated_at": now,
            },
        )
        return OrganizationMember(
            organization_id=organization_id,
            user_id=data.user_id,
            role=data.role,
            created_at=now,
            updated_at=now,
        )

    def update_member(
        self, organization_id: str, user_id: str, data: OrganizationMemberUpdate
    ) -> OrganizationMember | None:
        now = utc_now()
        existing = self.get_member(organization_id, user_id)
        if existing is None:
            return None
        self._ch.command(
            _MEMBER_INSERT,
            parameters={
                "organization_id": organization_id,
                "user_id": user_id,
                "role": data.role.name,
                "created_at": existing.created_at or now,
                "updated_at": now,
            },
        )
        return OrganizationMember(
            organization_id=organization_id,
            user_id=user_id,
            role=data.role,
            created_at=existing.created_at or now,
            updated_at=now,
        )

    def get_member(self, organization_id: str, user_id: str) -> OrganizationMember | None:
        rows = self._ch.query(
            f"SELECT {_MEMBER_COLS} FROM dim_organization_member FINAL"
            " WHERE organization_id = {oid:String} AND user_id = {uid:String}",
            parameters={"oid": organization_id, "uid": user_id},
        )
        for r in rows.named_results():
            return _row_to_member(r)
        return None

    def remove_member(self, organization_id: str, user_id: str) -> bool:
        existing = self.get_member(organization_id, user_id)
        if existing is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_organization_member DELETE"
            " WHERE organization_id = {oid:String} AND user_id = {uid:String}",
            parameters={"oid": organization_id, "uid": user_id},
        )
        return True

    # Shop Accounts
    def list_shop_accounts(self, organization_id: str | None = None) -> list[ShopAccount]:
        where = ""
        params: dict[str, object] = {}
        if organization_id:
            where = " WHERE organization_id = {oid:String}"
            params["oid"] = organization_id
        rows = self._ch.query(
            f"SELECT {_ACCT_COLS} FROM dim_account FINAL" + where + " ORDER BY created_at",
            parameters=params,
        )
        return [_row_to_account(r) for r in rows.named_results()]

    def get_shop_account(
        self, account_id: str, marketplace: str, organization_id: str | None = None
    ) -> ShopAccount | None:
        org_clause = " AND organization_id = {oid:String}" if organization_id else ""
        rows = self._ch.query(
            f"SELECT {_ACCT_COLS} FROM dim_account FINAL"
            " WHERE account_id = {aid:String} AND marketplace = {mp:String}" + org_clause,
            parameters={"aid": account_id, "mp": marketplace, "oid": organization_id or ""},
        )
        for r in rows.named_results():
            return _row_to_account(r)
        return None

    def create_shop_account(
        self, data: ShopAccountCreate, organization_id: str = "default"
    ) -> ShopAccount:
        now = utc_now()
        self._ch.command(
            _ACCT_INSERT,
            parameters={
                "account_id": data.account_id,
                "marketplace": data.marketplace,
                "organization_id": organization_id,
                "title": data.title,
                "created_at": now,
            },
        )
        return ShopAccount(
            account_id=data.account_id,
            marketplace=data.marketplace,
            organization_id=organization_id,
            title=data.title,
            is_active=True,
            created_at=now,
        )

    def update_shop_account(
        self,
        account_id: str,
        marketplace: str,
        data: ShopAccountUpdate,
        organization_id: str | None = None,
    ) -> ShopAccount | None:
        existing = self.get_shop_account(account_id, marketplace, organization_id)
        if existing is None:
            return None
        now = utc_now()
        title = data.title if data.title is not None else existing.title
        self._ch.command(
            _ACCT_INSERT,
            parameters={
                "account_id": account_id,
                "marketplace": marketplace,
                "organization_id": existing.organization_id,
                "title": title,
                "created_at": existing.created_at or now,
            },
        )
        return ShopAccount(
            account_id=account_id,
            marketplace=marketplace,
            organization_id=existing.organization_id,
            title=title,
            is_active=True,
            created_at=existing.created_at or now,
        )


def _row_to_org(r: dict[str, Any]) -> Organization:
    return Organization(
        organization_id=r["organization_id"],
        name=r["name"],
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


def _row_to_member(r: dict[str, Any]) -> OrganizationMember:
    return OrganizationMember(
        organization_id=r["organization_id"],
        user_id=r["user_id"],
        role=OrgMemberRole.parse(r["role"]),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


def _row_to_account(r: dict[str, Any]) -> ShopAccount:
    return ShopAccount(
        account_id=r["account_id"],
        marketplace=r["marketplace"],
        organization_id=r.get("organization_id", "default"),
        title=r["title"],
        created_at=r.get("created_at"),
    )
