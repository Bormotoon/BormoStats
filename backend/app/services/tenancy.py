"""Tenant scoping helpers.

Marketplace data (marts, rules, campaigns) is keyed by ``(marketplace, account_id)``;
an account belongs to exactly one organization via ``dim_account.organization_id``.
All tenant filters funnel through this module so the rule lives in one place.
"""

from __future__ import annotations

from clickhouse_connect.driver import Client

from common.tenancy_sql import account_scope_sql

__all__ = [
    "AccountAccessError",
    "account_scope_pyformat",
    "account_scope_sql",
    "ensure_account_access",
    "list_organization_accounts",
]


class AccountAccessError(LookupError):
    """Raised when an account does not exist or belongs to another organization."""


def account_scope_pyformat(organization_param: str = "organization_id", alias: str = "") -> str:
    """Same filter for SQL files that use client-side ``%(name)s`` parameters."""
    prefix = f"{alias}." if alias else ""
    return (
        f"({prefix}marketplace, {prefix}account_id) IN ("
        "SELECT marketplace, account_id FROM dim_account FINAL"
        f" WHERE organization_id = %({organization_param})s)"
    )


def ensure_account_access(
    ch: Client, organization_id: str, marketplace: str, account_id: str
) -> None:
    rows = ch.query(
        "SELECT count() FROM dim_account FINAL"
        " WHERE organization_id = {oid:String} AND marketplace = {mp:String}"
        " AND account_id = {aid:String}",
        parameters={"oid": organization_id, "mp": marketplace, "aid": account_id},
    )
    count = rows.result_rows[0][0] if rows.result_rows else 0
    if not count:
        raise AccountAccessError(f"account {marketplace}/{account_id} is not available")


def list_organization_accounts(ch: Client, organization_id: str) -> list[dict[str, str]]:
    rows = ch.query(
        "SELECT account_id, marketplace, organization_id, title, created_at"
        " FROM dim_account FINAL WHERE organization_id = {oid:String}"
        " ORDER BY marketplace, title",
        parameters={"oid": organization_id},
    )
    return [
        {
            "account_id": r[0],
            "marketplace": r[1],
            "organization_id": r[2],
            "title": r[3],
            "created_at": str(r[4]) if r[4] else "",
        }
        for r in rows.result_rows
    ]
