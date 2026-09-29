"""Bidder: ad campaigns and bid rules, scoped to one organization."""

from __future__ import annotations

import uuid
from typing import Any

from app.db.ch import insert_values_sql, utc_now
from app.models.bidder import AdCampaign, AdRule, AdRuleCreate, AdRuleUpdate
from app.models.marketplace_actions import MarketplaceAction
from app.services.marketplace_actions import list_marketplace_actions
from app.services.tenancy import account_scope_sql, ensure_account_access
from clickhouse_connect.driver import Client

_CAMP_COLUMNS: tuple[tuple[str, str], ...] = (
    ("campaign_id", "String"),
    ("marketplace", "String"),
    ("account_id", "String"),
    ("title", "String"),
    ("status", "String"),
    ("daily_budget", "Nullable(Float64)"),
    ("current_cpm", "Nullable(Float64)"),
    ("current_cpc", "Nullable(Float64)"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_RULE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("rule_id", "String"),
    ("campaign_id", "String"),
    ("marketplace", "String"),
    ("account_id", "String"),
    ("target_cpm", "Float64"),
    ("max_cpm", "Float64"),
    ("target_position", "UInt8"),
    ("product_id", "String"),
    ("placement", "String"),
    ("is_active", "UInt8"),
    ("dry_run", "UInt8"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_CAMP_COLS = ", ".join(name for name, _ in _CAMP_COLUMNS)
_RULE_COLS = ", ".join(name for name, _ in _RULE_COLUMNS)
_CAMP_INSERT = insert_values_sql("dim_ad_campaign", _CAMP_COLUMNS)
_RULE_INSERT = insert_values_sql("dim_ad_rule", _RULE_COLUMNS)


class BidderService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    def _filters(
        self, marketplace: str | None, account_id: str | None
    ) -> tuple[str, dict[str, object]]:
        where = [account_scope_sql("oid")]
        params: dict[str, object] = {"oid": self._org}
        if marketplace:
            where.append("marketplace = {mp:String}")
            params["mp"] = marketplace
        if account_id:
            where.append("account_id = {aid:String}")
            params["aid"] = account_id
        return " WHERE " + " AND ".join(where), params

    def list_campaigns(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[AdCampaign]:
        clause, params = self._filters(marketplace, account_id)
        rows = self._ch.query(
            f"SELECT {_CAMP_COLS} FROM dim_ad_campaign FINAL{clause} ORDER BY marketplace, title",
            parameters=params,
        )
        return [_row_to_campaign(r) for r in rows.named_results()]

    def list_rules(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[AdRule]:
        clause, params = self._filters(marketplace, account_id)
        rows = self._ch.query(
            f"SELECT {_RULE_COLS} FROM dim_ad_rule FINAL{clause} ORDER BY marketplace, campaign_id",
            parameters=params,
        )
        return [_row_to_rule(r) for r in rows.named_results()]

    def get_rule(self, rule_id: str) -> AdRule | None:
        clause, params = self._filters(None, None)
        rows = self._ch.query(
            f"SELECT {_RULE_COLS} FROM dim_ad_rule FINAL{clause} AND rule_id = {{rid:String}}"
            " LIMIT 1",
            parameters={**params, "rid": rule_id},
        )
        for r in rows.named_results():
            return _row_to_rule(r)
        return None

    def create_rule(self, data: AdRuleCreate) -> AdRule:
        ensure_account_access(self._ch, self._org, data.marketplace, data.account_id)
        now = utc_now()
        rule = AdRule(
            rule_id=str(uuid.uuid4()),
            campaign_id=data.campaign_id,
            marketplace=data.marketplace,
            account_id=data.account_id,
            target_cpm=data.target_cpm,
            max_cpm=data.max_cpm,
            target_position=data.target_position,
            product_id=data.product_id,
            placement=data.placement,
            is_active=True,
            dry_run=data.dry_run,
            created_at=now,
            updated_at=now,
        )
        self._write_rule(rule)
        return rule

    def update_rule(self, rule_id: str, data: AdRuleUpdate) -> AdRule | None:
        existing = self.get_rule(rule_id)
        if existing is None:
            return None
        changes = data.model_dump(exclude_none=True)
        rule = existing.model_copy(update={**changes, "updated_at": utc_now()})
        if rule.created_at is None:
            rule = rule.model_copy(update={"created_at": rule.updated_at})
        self._write_rule(rule)
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        existing = self.get_rule(rule_id)
        if existing is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_ad_rule DELETE WHERE rule_id = {rid:String}",
            parameters={"rid": rule_id},
        )
        return True

    def sync_campaigns(self, campaigns: list[AdCampaign]) -> int:
        for account in {(c.marketplace, c.account_id) for c in campaigns}:
            ensure_account_access(self._ch, self._org, *account)
        now = utc_now()
        for c in campaigns:
            self._ch.command(
                _CAMP_INSERT,
                parameters={
                    "campaign_id": c.campaign_id,
                    "marketplace": c.marketplace,
                    "account_id": c.account_id,
                    "title": c.title,
                    "status": c.status,
                    "daily_budget": c.daily_budget,
                    "current_cpm": c.current_cpm,
                    "current_cpc": c.current_cpc,
                    "created_at": c.created_at or now,
                    "updated_at": now,
                },
            )
        return len(campaigns)

    def list_actions(self, limit: int = 200) -> list[MarketplaceAction]:
        return list_marketplace_actions(self._ch, self._org, source="bidder", limit=limit)

    def _write_rule(self, rule: AdRule) -> None:
        self._ch.command(
            _RULE_INSERT,
            parameters={
                "rule_id": rule.rule_id,
                "campaign_id": rule.campaign_id,
                "marketplace": rule.marketplace,
                "account_id": rule.account_id,
                "target_cpm": rule.target_cpm,
                "max_cpm": rule.max_cpm,
                "target_position": rule.target_position,
                "product_id": rule.product_id,
                "placement": rule.placement,
                "is_active": 1 if rule.is_active else 0,
                "dry_run": 1 if rule.dry_run else 0,
                "created_at": rule.created_at,
                "updated_at": rule.updated_at,
            },
        )


def _row_to_campaign(r: dict[str, Any]) -> AdCampaign:
    return AdCampaign(
        campaign_id=r["campaign_id"],
        marketplace=r["marketplace"],
        account_id=r["account_id"],
        title=r["title"],
        status=r["status"],
        daily_budget=r.get("daily_budget"),
        current_cpm=r.get("current_cpm"),
        current_cpc=r.get("current_cpc"),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


def _row_to_rule(r: dict[str, Any]) -> AdRule:
    return AdRule(
        rule_id=r["rule_id"],
        campaign_id=r["campaign_id"],
        marketplace=r["marketplace"],
        account_id=r["account_id"],
        target_cpm=r["target_cpm"],
        max_cpm=r["max_cpm"],
        target_position=r["target_position"],
        product_id=r.get("product_id") or "",
        placement=r.get("placement") or "combined",
        is_active=bool(r["is_active"]),
        dry_run=bool(r.get("dry_run", 1)),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )
