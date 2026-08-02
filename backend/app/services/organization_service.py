from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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

_ORG_COLS = "organization_id, name, created_at, updated_at"
_ORG_INSERT = (
    "INSERT INTO dim_organization ({cols})"
    " VALUES ({oid:String}, {name:String}, {created:DateTime}, {now:DateTime})"
)

_MEMBER_COLS = "organization_id, user_id, role, created_at, updated_at"
_MEMBER_INSERT = (
    "INSERT INTO dim_organization_member ({cols})"
    " VALUES ({oid:String}, {uid:String}, {role:Int8}, {created:DateTime}, {now:DateTime})"
)

_ACCT_COLS = "account_id, marketplace, organization_id, title, created_at"
_ACCT_INSERT = (
    "INSERT INTO dim_account ({cols})"
    " VALUES ({aid:String}, {mp:String}, {oid:String}, {title:String}, {created:DateTime})"
)


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
        now = datetime.utcnow()
        org_id = str(uuid.uuid4())[:8]
        self._ch.command(
            _ORG_INSERT.format(cols=_ORG_COLS),
            parameters={
                "oid": org_id,
                "name": data.name,
                "created": now,
                "now": now,
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
        now = datetime.utcnow()
        name = data.name if data.name is not None else existing.name
        self._ch.command(
            _ORG_INSERT.format(cols=_ORG_COLS),
            parameters={
                "oid": organization_id,
                "name": name,
                "created": existing.created_at or now,
                "now": now,
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
            "ALTER TABLE dim_organization DELETE WHERE organization_id = %(oid)s",
            parameters={"oid": organization_id},
        )
        self._ch.command(
            "ALTER TABLE dim_organization_member DELETE WHERE organization_id = %(oid)s",
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
        now = datetime.utcnow()
        self._ch.command(
            _MEMBER_INSERT.format(cols=_MEMBER_COLS),
            parameters={
                "oid": organization_id,
                "uid": data.user_id,
                "role": data.role.value,
                "created": now,
                "now": now,
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
        now = datetime.utcnow()
        existing = self.get_member(organization_id, user_id)
        if existing is None:
            return None
        self._ch.command(
            _MEMBER_INSERT.format(cols=_MEMBER_COLS),
            parameters={
                "oid": organization_id,
                "uid": user_id,
                "role": data.role.value,
                "created": existing.created_at or now,
                "now": now,
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
            " WHERE organization_id = %(oid)s AND user_id = %(uid)s",
            parameters={"oid": organization_id, "uid": user_id},
        )
        return True

    # Shop Accounts
    def list_shop_accounts(self, organization_id: str | None = None) -> list[ShopAccount]:
        where = ""
        params: dict[str, object] = {}
        if organization_id:
            where = " WHERE organization_id = %(oid)s"
            params["oid"] = organization_id
        rows = self._ch.query(
            f"SELECT {_ACCT_COLS} FROM dim_account FINAL" + where + " ORDER BY created_at",
            parameters=params,
        )
        return [_row_to_account(r) for r in rows.named_results()]

    def get_shop_account(self, account_id: str, marketplace: str) -> ShopAccount | None:
        rows = self._ch.query(
            f"SELECT {_ACCT_COLS} FROM dim_account FINAL"
            " WHERE account_id = {aid:String} AND marketplace = {mp:String}",
            parameters={"aid": account_id, "mp": marketplace},
        )
        for r in rows.named_results():
            return _row_to_account(r)
        return None

    def create_shop_account(
        self, data: ShopAccountCreate, organization_id: str = "default"
    ) -> ShopAccount:
        now = datetime.utcnow()
        self._ch.command(
            _ACCT_INSERT.format(cols=_ACCT_COLS),
            parameters={
                "aid": data.account_id,
                "mp": data.marketplace,
                "oid": organization_id,
                "title": data.title,
                "created": now,
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
        self, account_id: str, marketplace: str, data: ShopAccountUpdate
    ) -> ShopAccount | None:
        existing = self.get_shop_account(account_id, marketplace)
        if existing is None:
            return None
        now = datetime.utcnow()
        title = data.title if data.title is not None else existing.title
        self._ch.command(
            _ACCT_INSERT.format(cols=_ACCT_COLS),
            parameters={
                "aid": account_id,
                "mp": marketplace,
                "oid": existing.organization_id,
                "title": title,
                "created": existing.created_at or now,
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
        role=OrgMemberRole(r["role"]),
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
