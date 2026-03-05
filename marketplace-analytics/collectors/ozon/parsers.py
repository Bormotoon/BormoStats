"""Ozon response parsers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from collectors.common.time import as_ch_datetime, parse_dt


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        return parse_dt(value)
    return None


def parse_postings(
    records: list[dict[str, Any]],
    run_id: str,
    account_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    postings_rows: list[dict[str, Any]] = []
    items_rows: list[dict[str, Any]] = []

    for posting in records:
        created_at = _to_datetime(posting.get("created_at")) or datetime.now(UTC)
        in_process_at = _to_datetime(posting.get("in_process_at"))
        shipped_at = _to_datetime(posting.get("shipment_date"))
        delivered_at = _to_datetime(posting.get("delivering_date"))
        canceled_at = _to_datetime(posting.get("cancel_reason_id"))

        posting_number = str(posting.get("posting_number") or "")
        postings_rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "posting_number": posting_number,
                "status": str(posting.get("status") or "unknown"),
                "created_at": as_ch_datetime(created_at),
                "in_process_at": as_ch_datetime(in_process_at) if in_process_at else None,
                "shipped_at": as_ch_datetime(shipped_at) if shipped_at else None,
                "delivered_at": as_ch_datetime(delivered_at) if delivered_at else None,
                "canceled_at": as_ch_datetime(canceled_at) if canceled_at else None,
                "ozon_warehouse_id": _safe_int(posting.get("warehouse_id")) or None,
                "payload": json.dumps(posting, ensure_ascii=True),
            }
        )

        products = posting.get("products")
        if not isinstance(products, list):
            continue

        for product in products:
            items_rows.append(
                {
                    "run_id": run_id,
                    "account_id": account_id,
                    "posting_number": posting_number,
                    "ozon_product_id": _safe_int(product.get("product_id")),
                    "offer_id": product.get("offer_id"),
                    "name": product.get("name"),
                    "quantity": max(1, _safe_int(product.get("quantity"), 1)),
                    "price": _safe_float(product.get("price")),
                    "payout": _safe_float(product.get("payout") or product.get("price")),
                    "payload": json.dumps(product, ensure_ascii=True),
                }
            )

    return postings_rows, items_rows


def parse_stocks(
    records: list[dict[str, Any]],
    run_id: str,
    account_id: str,
    snapshot_ts: datetime,
) -> list[dict[str, Any]]:
    snap = as_ch_datetime(snapshot_ts)
    rows: list[dict[str, Any]] = []
    for item in records:
        stocks = item.get("stocks")
        if isinstance(stocks, list) and stocks:
            for stock in stocks:
                rows.append(
                    {
                        "run_id": run_id,
                        "account_id": account_id,
                        "snapshot_ts": snap,
                        "ozon_product_id": _safe_int(item.get("product_id")),
                        "offer_id": item.get("offer_id"),
                        "warehouse_id": _safe_int(stock.get("warehouse_id")) or None,
                        "present": _safe_int(stock.get("present")),
                        "reserved": _safe_int(stock.get("reserved")),
                        "payload": json.dumps({"item": item, "stock": stock}, ensure_ascii=True),
                    }
                )
        else:
            rows.append(
                {
                    "run_id": run_id,
                    "account_id": account_id,
                    "snapshot_ts": snap,
                    "ozon_product_id": _safe_int(item.get("product_id")),
                    "offer_id": item.get("offer_id"),
                    "warehouse_id": _safe_int(item.get("warehouse_id")) or None,
                    "present": _safe_int(item.get("present")),
                    "reserved": _safe_int(item.get("reserved")),
                    "payload": json.dumps(item, ensure_ascii=True),
                }
            )
    return rows


def parse_ads_daily(records: list[dict[str, Any]], run_id: str, account_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in records:
        day_raw = item.get("date") or item.get("day")
        day = (_to_datetime(day_raw) or datetime.now(UTC)).date()
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "day": day,
                "campaign_id": str(item.get("campaign_id") or item.get("id") or "unknown"),
                "impressions": _safe_int(item.get("impressions")),
                "clicks": _safe_int(item.get("clicks")),
                "cost": _safe_float(item.get("cost") or item.get("money_spent")),
                "orders": _safe_int(item.get("orders") or item.get("attributed_orders")),
                "revenue": _safe_float(item.get("revenue") or item.get("attributed_revenue")),
                "payload": json.dumps(item, ensure_ascii=True),
            }
        )
    return rows
