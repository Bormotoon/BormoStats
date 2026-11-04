"""Event-day finance and observed stock metrics for the Ozon funnel."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from common.article_economics import EXPENSES, AccrualEconomics


def campaign_kind(payload: dict[str, Any]) -> str | None:
    """CPC is a payment method; split it by the actual bidding strategy."""
    if payload.get("PaymentType", payload.get("paymentType")) != "CPC":
        return None
    strategy = payload.get("productAutopilotStrategy")
    if strategy == "TARGET_BIDS":
        return "cpc"
    if strategy in ("MAX_CLICKS", "TOP_MAX_CLICKS", "TARGET_CIR"):
        return "auto"
    return None


def campaign_metadata_rows(
    account: str, campaigns: Iterable[dict[str, Any]], fetched_at: datetime | None = None
) -> list[list[Any]]:
    now_utc = fetched_at or datetime.now(UTC)
    result: list[list[Any]] = []
    for record in campaigns:
        effective_str = record.get("updatedAt") or record.get("createdAt")
        effective = (
            datetime.fromisoformat(effective_str.replace("Z", "+00:00"))
            if effective_str
            else now_utc
        )
        result.append(
            [
                account,
                str(record["id"]),
                effective,
                json.dumps(record, ensure_ascii=False),
                now_utc,
            ]
        )
    return result


def finance_days(
    records: Iterable[tuple[str, str]], buyouts: Iterable[tuple[str, Any, str]] = ()
) -> list[dict[str, Any]]:
    """Keep account and event day; let the finance engine prevent buyout overlap."""
    engines: dict[tuple[str, str], AccrualEconomics] = defaultdict(AccrualEconomics)
    for account, raw in records:
        payload = json.loads(raw, parse_float=Decimal)
        engines[(account, str(payload["date"])[:10])].add(payload)
    # A buyout can overlap a domestic sale booked on a different day.
    seen: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for account, day, raw in buyouts:
        engine = engines[(account, str(day))]
        # Only match domestic postings in the same account.
        engine.domestic_sales.update(
            {
                k: v
                for (a, _), e in engines.items()
                if a == account
                for k, v in e.domestic_sales.items()
            }
        )
        engine.seen_buyouts = seen.setdefault(account, {})
        # Already represented domestic sales must stay on their original day.
        payload = json.loads(raw, parse_float=Decimal)
        payload["products"] = [
            r
            for r in payload.get("products", [])
            if (str(r.get("posting_number")), str(r.get("sku"))) not in engine.domestic_sales
        ]
        engine.add_buyouts(day, payload)
    result: list[dict[str, Any]] = []
    for (account, day), engine in engines.items():
        engine.allocate()
        for sku, row in engine.rows.items():
            if sku == "unallocated":
                continue
            sold = row["sales_qty"] + row["sales_cis"]
            returned = -row["returns_qty"]
            result.append(
                dict(
                    account_id=account,
                    day=day,
                    sku=sku,
                    sold=float(sold),
                    returned=float(returned),
                    revenue=float(row["revenue"]),
                    buyer=float(row["buyer_revenue"]),
                    mp_cost=float(
                        row["commission"] + sum(row[k] for k in EXPENSES if k != "marketing")
                    ),
                )
            )
    return result


def stock_metrics(parts: Iterable[dict[str, Any]]) -> dict[str, int | None]:
    """Missing analytics fields stay unknown. Never count all stock as FBO."""
    result: dict[str, int | None] = dict(stock=0, stockFbs=0, transit=0, reverse=0)
    analytics = False
    for p in parts:
        scheme = str(p.get("type", "")).lower()
        if scheme not in ("fbo", "fbs"):
            continue
        key = "stock" if scheme == "fbo" else "stockFbs"
        val = result[key]
        if val is not None:
            result[key] = val + int(p.get("available_stock_count", p.get("present", 0)))
        if "transit_stock_count" in p:
            analytics = True
            tr = result["transit"] or 0
            rev = result["reverse"] or 0
            result["transit"] = tr + int(p["transit_stock_count"])
            result["reverse"] = rev + int(p.get("return_from_customer_stock_count", 0))
    if not analytics:
        result["transit"] = result["reverse"] = None
    return result
