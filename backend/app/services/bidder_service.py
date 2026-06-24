from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.models.bidder import AdCampaign, AdRule, AdRuleCreate, AdRuleUpdate
from clickhouse_connect.driver import Client

_CAMP_COLS = "campaign_id, marketplace, account_id, title, status, daily_budget, current_cpm, current_cpc, created_at, updated_at"
_RULE_COLS = "rule_id, campaign_id, marketplace, account_id, target_cpm, max_cpm, target_position, is_active, created_at, updated_at"

_RULE_INSERT = (
    "INSERT INTO dim_ad_rule ({cols})"
    " VALUES ({rid:String}, {cid:String}, {mp:String}, {aid:String},"
    " {tcpm:Float64}, {mcpm:Float64}, {tpos:UInt8}, {active:UInt8},"
    " {created:DateTime}, {now:DateTime})"
)


class BidderService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    def list_campaigns(self, marketplace: str | None = None, account_id: str | None = None) -> list[AdCampaign]:
        where = []
        params: dict[str, object] = {}
        if marketplace:
            where.append("marketplace = %(mp)s")
            params["mp"] = marketplace
        if account_id:
            where.append("account_id = %(aid)s")
            params["aid"] = account_id
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        rows = self._ch.query(
            f"SELECT {_CAMP_COLS} FROM dim_ad_campaign FINAL" + clause + " ORDER BY marketplace, title",
            parameters=params,
        )
        return [_row_to_campaign(r) for r in rows.named_results()]

    def list_rules(self, marketplace: str | None = None, account_id: str | None = None) -> list[AdRule]:
        where = []
        params: dict[str, object] = {}
        if marketplace:
            where.append("marketplace = %(mp)s")
            params["mp"] = marketplace
        if account_id:
            where.append("account_id = %(aid)s")
            params["aid"] = account_id
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        rows = self._ch.query(
            f"SELECT {_RULE_COLS} FROM dim_ad_rule FINAL" + clause + " ORDER BY marketplace, campaign_id",
            parameters=params,
        )
        return [_row_to_rule(r) for r in rows.named_results()]

    def get_rule(self, rule_id: str) -> AdRule | None:
        rows = self._ch.query(
            f"SELECT {_RULE_COLS} FROM dim_ad_rule FINAL WHERE rule_id = {{rid:String}}",
            parameters={"rid": rule_id},
        )
        for r in rows.named_results():
            return _row_to_rule(r)
        return None

    def create_rule(self, data: AdRuleCreate) -> AdRule:
        now = datetime.utcnow()
        rule_id = str(uuid.uuid4())[:8]
        self._ch.command(
            _RULE_INSERT.format(cols=_RULE_COLS),
            parameters={
                "rid": rule_id,
                "cid": data.campaign_id,
                "mp": data.marketplace,
                "aid": data.account_id,
                "tcpm": data.target_cpm,
                "mcpm": data.max_cpm,
                "tpos": data.target_position,
                "active": 1,
                "created": now,
                "now": now,
            },
        )
        return AdRule(
            rule_id=rule_id,
            campaign_id=data.campaign_id,
            marketplace=data.marketplace,
            account_id=data.account_id,
            target_cpm=data.target_cpm,
            max_cpm=data.max_cpm,
            target_position=data.target_position,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    def update_rule(self, rule_id: str, data: AdRuleUpdate) -> AdRule | None:
        existing = self.get_rule(rule_id)
        if existing is None:
            return None
        now = datetime.utcnow()
        target_cpm = data.target_cpm if data.target_cpm is not None else existing.target_cpm
        max_cpm = data.max_cpm if data.max_cpm is not None else existing.max_cpm
        target_position = data.target_position if data.target_position is not None else existing.target_position
        is_active = data.is_active if data.is_active is not None else existing.is_active
        self._ch.command(
            _RULE_INSERT.format(cols=_RULE_COLS),
            parameters={
                "rid": rule_id,
                "cid": existing.campaign_id,
                "mp": existing.marketplace,
                "aid": existing.account_id,
                "tcpm": target_cpm,
                "mcpm": max_cpm,
                "tpos": target_position,
                "active": 1 if is_active else 0,
                "created": existing.created_at or now,
                "now": now,
            },
        )
        return AdRule(
            rule_id=rule_id,
            campaign_id=existing.campaign_id,
            marketplace=existing.marketplace,
            account_id=existing.account_id,
            target_cpm=target_cpm,
            max_cpm=max_cpm,
            target_position=target_position,
            is_active=is_active,
            created_at=existing.created_at or now,
            updated_at=now,
        )

    def delete_rule(self, rule_id: str) -> bool:
        existing = self.get_rule(rule_id)
        if existing is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_ad_rule DELETE WHERE rule_id = %(rid)s",
            parameters={"rid": rule_id},
        )
        return True

    def sync_campaigns(self, campaigns: list[AdCampaign]) -> None:
        now = datetime.utcnow()
        for c in campaigns:
            self._ch.command(
                "INSERT INTO dim_ad_campaign ({cols})"
                " VALUES ({cid:String}, {mp:String}, {aid:String}, {title:String},"
                " {status:String}, {budget:Nullable(Float64)}, {cpm:Nullable(Float64)},"
                " {cpc:Nullable(Float64)}, {created:DateTime}, {now:DateTime})".format(cols=_CAMP_COLS),
                parameters={
                    "cid": c.campaign_id,
                    "mp": c.marketplace,
                    "aid": c.account_id,
                    "title": c.title,
                    "status": c.status,
                    "budget": c.daily_budget,
                    "cpm": c.current_cpm,
                    "cpc": c.current_cpc,
                    "created": now,
                    "now": now,
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
        is_active=bool(r["is_active"]),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )
