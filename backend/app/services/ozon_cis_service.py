"""Additional CIS receipts and COGS absent from domestic sale accruals."""

from __future__ import annotations

import contextlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from common.article_economics import number
from common.ozon_buyouts import parse_buyouts


def cis_adjustments(ch: Any, account_id: str, start: date, stop: date) -> dict[str, dict[str, Any]]:
    """Compute CIS buyout adjustments without date bounds on accrual search (Copilot #12, #13, #16)
    and properly track missing cost offers (Copilot #14).
    """
    params: dict[str, Any] = {"aid": account_id, "start": start, "stop": stop}
    snapshots: list[dict[str, Any]] = []
    cis_sql = (
        "SELECT day, posting_number, sku, offer_id, quantity, seller_price, "
        "amount, commission, payout, payload"
        " FROM raw_ozon_cis_buyouts FINAL WHERE account_id={aid:String}"
        " AND day BETWEEN {start:Date} AND {stop:Date} ORDER BY day"
    )
    with contextlib.suppress(Exception):
        snapshots = list(ch.query(cis_sql, parameters=params).named_results())

    if not snapshots:
        cis_fallback_sql = (
            "SELECT day, payload FROM raw_ozon_cis_buyouts FINAL"
            " WHERE account_id={aid:String}"
            " AND day BETWEEN {start:Date} AND {stop:Date} ORDER BY day"
        )
        with contextlib.suppress(Exception):
            snapshots = list(ch.query(cis_fallback_sql, parameters=params).named_results())

    if not snapshots:
        return {}

    cis_rows: list[dict[str, Any]] = []
    for snap in snapshots:
        day = snap["day"]
        if isinstance(day, str):
            day = date.fromisoformat(day[:10])
        payload_str = snap.get("payload")
        if payload_str and isinstance(payload_str, str) and payload_str.strip().startswith("{"):
            try:
                parsed = parse_buyouts(json.loads(payload_str, parse_float=Decimal))
                for item in parsed:
                    cis_rows.append({**item, "day": day})
                continue
            except Exception:
                pass
        if snap.get("posting_number") and snap.get("sku"):
            qty = number(snap.get("quantity") or 1)
            seller_price = number(snap.get("seller_price") or 0)
            amount = number(snap.get("amount") or 0)
            gross = seller_price * qty
            cis_rows.append(
                {
                    "day": day,
                    "posting_number": str(snap["posting_number"]),
                    "sku": str(snap["sku"]),
                    "offer_id": str(snap.get("offer_id") or ""),
                    "quantity": qty,
                    "gross": gross,
                    "receipt": amount,
                    "deduction": gross - amount,
                }
            )

    if not cis_rows:
        return {}

    # 1. Deduplicate against domestic accruals WITHOUT bounding by date_from (Copilot #12, #13, #16)
    cis_postings = sorted({str(r["posting_number"]) for r in cis_rows if r.get("posting_number")})
    already_accrued_postings: set[str] = set()
    if cis_postings:
        try:
            found = ch.query(
                "SELECT DISTINCT JSONExtractString(payload, 'unit_number') AS posting_number"
                " FROM raw_ozon_finance_ops FINAL"
                " WHERE account_id IN {aids:Array(String)}"
                "   AND source = 'accrual_by_day'"
                "   AND JSONExtractString(payload, 'accrued_category') = 'POSTING'"
                "   AND JSONExtractString(payload, 'unit_number') IN {postings:Array(String)}",
                parameters={"aids": [account_id], "postings": cis_postings},
            ).result_rows
            already_accrued_postings = {str(row[0]) for row in found if row[0]}
        except Exception:
            pass

    # 2. Fetch product costs for SKU
    costs: dict[str, Decimal] = {}
    try:
        cost_sql = (
            "SELECT p.product_id AS product_id,"
            " if(ifNull(oc.cost_price_rub,0)>0,oc.cost_price_rub,"
            "ifNull(c.cost_price_rub,0)) AS cost"
            " FROM dim_product AS p FINAL"
            " LEFT JOIN v_offer_cost AS oc"
            " ON p.marketplace=oc.marketplace AND p.account_id=oc.account_id"
            " AND p.product_id=oc.product_id"
            " LEFT JOIN dim_product_cost AS c FINAL"
            " ON p.marketplace=c.marketplace AND p.product_id=toString(c.product_id)"
            " WHERE p.marketplace='ozon' AND p.account_id={aid:String}"
        )
        cost_rows = ch.query(cost_sql, parameters={"aid": account_id}).named_results()
        costs = {str(r["product_id"]): number(r["cost"]) for r in cost_rows}
    except Exception:
        pass

    # 3. Aggregate adjustments by day
    result: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "receipts": Decimal(0),
            "cogs": Decimal(0),
            "qty": Decimal(0),
            "revenue": Decimal(0),
            "commission": Decimal(0),
            "missing_costs": 0,
            "missing_cost_offers": set(),
        }
    )

    for r in cis_rows:
        posting = str(r["posting_number"])
        if posting in already_accrued_postings:
            continue

        day_key = r["day"].isoformat() if isinstance(r["day"], date) else str(r["day"])
        target = result[day_key]

        qty = Decimal(str(r["quantity"]))
        gross = Decimal(str(r["gross"]))
        receipt = Decimal(str(r["receipt"]))
        deduction = Decimal(str(r["deduction"]))

        target["qty"] += qty
        target["revenue"] += gross
        target["receipts"] += receipt
        target["commission"] += deduction

        sku_str = str(r["sku"])
        unit_cost = costs.get(sku_str, Decimal(0))
        if unit_cost <= 0:
            target["missing_costs"] += 1
            target["missing_cost_offers"].add(r.get("offer_id") or sku_str)
        else:
            target["cogs"] += qty * unit_cost

    return result
