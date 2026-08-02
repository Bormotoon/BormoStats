from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.models.repricer import BreakevenRow, PriceRule, PriceRuleCreate, PriceRuleUpdate
from clickhouse_connect.driver import Client

_RULE_COLS = (
    "rule_id, marketplace, account_id, product_id, min_price, max_price, "
    "target_margin_percent, is_active, created_at, updated_at"
)
_RULE_INSERT = (
    "INSERT INTO dim_price_rule ({cols})"
    " VALUES ({rid:String}, {mp:String}, {aid:String}, {pid:String},"
    " {minp:Float64}, {maxp:Float64}, {margin:Float64}, {active:UInt8},"
    " {created:DateTime}, {now:DateTime})"
)

_BE_COLS = (
    "day, marketplace, account_id, product_id, current_price, cost_price, commission_pct, "
    "logistics_rub, breakeven_price, min_recommended_price"
)


class RepricerService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    def list_rules(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[PriceRule]:
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
            f"SELECT {_RULE_COLS} FROM dim_price_rule FINAL"
            + clause
            + " ORDER BY marketplace, product_id",
            parameters=params,
        )
        return [_row_to_rule(r) for r in rows.named_results()]

    def get_rule(self, rule_id: str) -> PriceRule | None:
        rows = self._ch.query(
            f"SELECT {_RULE_COLS} FROM dim_price_rule FINAL WHERE rule_id = {{rid:String}}",
            parameters={"rid": rule_id},
        )
        for r in rows.named_results():
            return _row_to_rule(r)
        return None

    def create_rule(self, data: PriceRuleCreate) -> PriceRule:
        now = datetime.utcnow()
        rule_id = str(uuid.uuid4())[:8]
        self._ch.command(
            _RULE_INSERT.format(cols=_RULE_COLS),
            parameters={
                "rid": rule_id,
                "mp": data.marketplace,
                "aid": data.account_id,
                "pid": data.product_id,
                "minp": data.min_price,
                "maxp": data.max_price,
                "margin": data.target_margin_percent,
                "active": 1,
                "created": now,
                "now": now,
            },
        )
        return PriceRule(
            rule_id=rule_id,
            marketplace=data.marketplace,
            account_id=data.account_id,
            product_id=data.product_id,
            min_price=data.min_price,
            max_price=data.max_price,
            target_margin_percent=data.target_margin_percent,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    def update_rule(self, rule_id: str, data: PriceRuleUpdate) -> PriceRule | None:
        existing = self.get_rule(rule_id)
        if existing is None:
            return None
        now = datetime.utcnow()
        min_price = data.min_price if data.min_price is not None else existing.min_price
        max_price = data.max_price if data.max_price is not None else existing.max_price
        margin = (
            data.target_margin_percent
            if data.target_margin_percent is not None
            else existing.target_margin_percent
        )
        is_active = data.is_active if data.is_active is not None else existing.is_active
        self._ch.command(
            _RULE_INSERT.format(cols=_RULE_COLS),
            parameters={
                "rid": rule_id,
                "mp": existing.marketplace,
                "aid": existing.account_id,
                "pid": existing.product_id,
                "minp": min_price,
                "maxp": max_price,
                "margin": margin,
                "active": 1 if is_active else 0,
                "created": existing.created_at or now,
                "now": now,
            },
        )
        return PriceRule(
            rule_id=rule_id,
            marketplace=existing.marketplace,
            account_id=existing.account_id,
            product_id=existing.product_id,
            min_price=min_price,
            max_price=max_price,
            target_margin_percent=margin,
            is_active=is_active,
            created_at=existing.created_at or now,
            updated_at=now,
        )

    def delete_rule(self, rule_id: str) -> bool:
        existing = self.get_rule(rule_id)
        if existing is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_price_rule DELETE WHERE rule_id = %(rid)s",
            parameters={"rid": rule_id},
        )
        return True

    def get_breakeven(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[BreakevenRow]:
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
            f"SELECT {_BE_COLS} FROM mrt_breakeven_daily FINAL"
            + clause
            + " ORDER BY breakeven_price DESC",
            parameters=params,
        )
        return [_row_to_breakeven(r) for r in rows.named_results()]


def _row_to_rule(r: dict[str, Any]) -> PriceRule:
    return PriceRule(
        rule_id=r["rule_id"],
        marketplace=r["marketplace"],
        account_id=r["account_id"],
        product_id=r["product_id"],
        min_price=r["min_price"],
        max_price=r["max_price"],
        target_margin_percent=r["target_margin_percent"],
        is_active=bool(r["is_active"]),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


def _row_to_breakeven(r: dict[str, Any]) -> BreakevenRow:
    return BreakevenRow(
        day=str(r["day"]),
        marketplace=r["marketplace"],
        account_id=r["account_id"],
        product_id=r["product_id"],
        current_price=float(r["current_price"]),
        cost_price=float(r["cost_price"]),
        commission_pct=float(r["commission_pct"]),
        logistics_rub=float(r["logistics_rub"]),
        breakeven_price=float(r["breakeven_price"]),
        min_recommended_price=float(r["min_recommended_price"]),
    )
