"""Read access to the bid/price change audit trail written by workers."""

from __future__ import annotations

from app.models.marketplace_actions import MarketplaceAction
from clickhouse_connect.driver import Client

_COLS = (
    "action_id, organization_id, source, rule_id, marketplace, account_id, target_type,"
    " target_id, before_value, after_value, dry_run, status, response_status, response_body,"
    " idempotency_key, created_at"
)


def list_marketplace_actions(
    ch: Client, organization_id: str, *, source: str, limit: int = 200
) -> list[MarketplaceAction]:
    rows = ch.query(
        f"SELECT {_COLS} FROM sys_marketplace_actions"
        " WHERE organization_id = {oid:String} AND source = {src:String}"
        " ORDER BY created_at DESC LIMIT {lim:UInt32}",
        parameters={"oid": organization_id, "src": source, "lim": limit},
    )
    return [MarketplaceAction(**{**r, "dry_run": bool(r["dry_run"])}) for r in rows.named_results()]
