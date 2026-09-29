"""Repricer: price rules and break-even analytics, scoped to one organization."""

from __future__ import annotations

import uuid
from typing import Any

from app.db.ch import PARTITION_LOCAL_FINAL, insert_values_sql, utc_now
from app.models.marketplace_actions import MarketplaceAction
from app.models.repricer import BreakevenRow, PriceRule, PriceRuleCreate, PriceRuleUpdate
from app.services.marketplace_actions import list_marketplace_actions
from app.services.tenancy import account_scope_sql, ensure_account_access
from clickhouse_connect.driver import Client

_RULE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("rule_id", "String"),
    ("marketplace", "String"),
    ("account_id", "String"),
    ("product_id", "String"),
    ("min_price", "Float64"),
    ("max_price", "Float64"),
    ("target_margin_percent", "Float64"),
    ("is_active", "UInt8"),
    ("dry_run", "UInt8"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_RULE_COLS = ", ".join(name for name, _ in _RULE_COLUMNS)
_RULE_INSERT = insert_values_sql("dim_price_rule", _RULE_COLUMNS)
_BE_COLS = (
    "day, marketplace, account_id, product_id, current_price, cost_price, commission_pct,"
    " logistics_rub, breakeven_price, min_recommended_price"
)


class RepricerService:
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

    def list_rules(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[PriceRule]:
        clause, params = self._filters(marketplace, account_id)
        rows = self._ch.query(
            f"SELECT {_RULE_COLS} FROM dim_price_rule FINAL{clause}"
            " ORDER BY marketplace, product_id",
            parameters=params,
        )
        return [_row_to_rule(r) for r in rows.named_results()]

    def get_rule(self, rule_id: str) -> PriceRule | None:
        clause, params = self._filters(None, None)
        rows = self._ch.query(
            f"SELECT {_RULE_COLS} FROM dim_price_rule FINAL{clause}"
            " AND rule_id = {rid:String} LIMIT 1",
            parameters={**params, "rid": rule_id},
        )
        for r in rows.named_results():
            return _row_to_rule(r)
        return None

    def create_rule(self, data: PriceRuleCreate) -> PriceRule:
        ensure_account_access(self._ch, self._org, data.marketplace, data.account_id)
        now = utc_now()
        rule = PriceRule(
            rule_id=str(uuid.uuid4()),
            marketplace=data.marketplace,
            account_id=data.account_id,
            product_id=data.product_id,
            min_price=data.min_price,
            max_price=data.max_price,
            target_margin_percent=data.target_margin_percent,
            is_active=True,
            dry_run=data.dry_run,
            created_at=now,
            updated_at=now,
        )
        self._write_rule(rule)
        return rule

    def update_rule(self, rule_id: str, data: PriceRuleUpdate) -> PriceRule | None:
        existing = self.get_rule(rule_id)
        if existing is None:
            return None
        now = utc_now()
        rule = existing.model_copy(
            update={
                **data.model_dump(exclude_none=True),
                "created_at": existing.created_at or now,
                "updated_at": now,
            }
        )
        self._write_rule(rule)
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        if self.get_rule(rule_id) is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_price_rule DELETE WHERE rule_id = {rid:String}",
            parameters={"rid": rule_id},
        )
        return True

    def get_breakeven(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[BreakevenRow]:
        clause, params = self._filters(marketplace, account_id)
        rows = self._ch.query(
            f"SELECT {_BE_COLS} FROM mrt_breakeven_daily FINAL{clause}"
            " ORDER BY breakeven_price DESC LIMIT 5000",
            parameters=params,
            settings=PARTITION_LOCAL_FINAL,
        )
        return [_row_to_breakeven(r) for r in rows.named_results()]

    def list_actions(self, limit: int = 200) -> list[MarketplaceAction]:
        return list_marketplace_actions(self._ch, self._org, source="repricer", limit=limit)

    def _write_rule(self, rule: PriceRule) -> None:
        self._ch.command(
            _RULE_INSERT,
            parameters={
                "rule_id": rule.rule_id,
                "marketplace": rule.marketplace,
                "account_id": rule.account_id,
                "product_id": rule.product_id,
                "min_price": rule.min_price,
                "max_price": rule.max_price,
                "target_margin_percent": rule.target_margin_percent,
                "is_active": 1 if rule.is_active else 0,
                "dry_run": 1 if rule.dry_run else 0,
                "created_at": rule.created_at,
                "updated_at": rule.updated_at,
            },
        )


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
        dry_run=bool(r.get("dry_run", 1)),
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
