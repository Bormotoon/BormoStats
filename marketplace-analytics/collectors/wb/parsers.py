"""WB response parsers."""

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


def _to_datetime(value: Any, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str):
        parsed = parse_dt(value)
        if parsed:
            return parsed
    return default or datetime.now(UTC)


def parse_sales(records: list[dict[str, Any]], run_id: str, account_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in records:
        last_change = _to_datetime(item.get("lastChangeDate") or item.get("lastChangeDt"))
        event_ts = _to_datetime(item.get("date"), default=last_change)
        quantity = _safe_int(item.get("quantity") or item.get("saleQty") or 1, 1)
        is_return = 1 if quantity < 0 or "возврат" in str(item.get("supplierOperName", "")).lower() else 0
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "srid": str(item.get("srid") or item.get("saleID") or item.get("gNumber") or ""),
                "last_change_ts": as_ch_datetime(last_change),
                "event_ts": as_ch_datetime(event_ts),
                "nm_id": _safe_int(item.get("nmId")),
                "chrt_id": _safe_int(item.get("chrtId")),
                "barcode": item.get("barcode"),
                "quantity": abs(quantity),
                "price_rub": _safe_float(item.get("forPay") or item.get("totalPrice") or item.get("priceWithDisc")),
                "payout_rub": _safe_float(item.get("ppvzForPay") or item.get("incomeID") or 0.0),
                "is_return": is_return,
                "payload": json.dumps(item, ensure_ascii=True),
            }
        )
    return rows


def parse_orders(records: list[dict[str, Any]], run_id: str, account_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in records:
        last_change = _to_datetime(item.get("lastChangeDate") or item.get("lastChangeDt"))
        event_ts = _to_datetime(item.get("date"), default=last_change)
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "srid": str(item.get("srid") or item.get("odid") or item.get("gNumber") or ""),
                "last_change_ts": as_ch_datetime(last_change),
                "event_ts": as_ch_datetime(event_ts),
                "nm_id": _safe_int(item.get("nmId")),
                "chrt_id": _safe_int(item.get("chrtId")),
                "quantity": max(1, _safe_int(item.get("quantity"), 1)),
                "price_rub": _safe_float(item.get("totalPrice") or item.get("priceWithDisc") or item.get("price")),
                "payload": json.dumps(item, ensure_ascii=True),
            }
        )
    return rows


def parse_stocks(
    records: list[dict[str, Any]],
    run_id: str,
    account_id: str,
    snapshot_ts: datetime,
) -> list[dict[str, Any]]:
    snap = as_ch_datetime(snapshot_ts)
    rows: list[dict[str, Any]] = []
    for item in records:
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "snapshot_ts": snap,
                "nm_id": _safe_int(item.get("nmId")) or None,
                "chrt_id": _safe_int(item.get("chrtId")),
                "sku": item.get("sku"),
                "warehouse_id": _safe_int(item.get("warehouseId")) or None,
                "amount": _safe_int(item.get("quantity") or item.get("quantityFull") or item.get("inWayToClient") or 0),
                "payload": json.dumps(item, ensure_ascii=True),
            }
        )
    return rows


def parse_funnel(records: list[dict[str, Any]], run_id: str, account_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in records:
        day_raw = item.get("date") or item.get("day")
        day_val = _to_datetime(day_raw).date()
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "day": day_val,
                "nm_id": _safe_int(item.get("nmId") or item.get("nm_id")),
                "open_card_count": _safe_int(item.get("openCardCount") or item.get("views")),
                "add_to_cart_count": _safe_int(item.get("addToCartCount") or item.get("addsToCart")),
                "orders_count": _safe_int(item.get("ordersCount") or item.get("orders")),
                "orders_sum_rub": _safe_float(item.get("ordersSumRub") or item.get("ordersSum") or item.get("ordersRevenue")),
                "buyouts_count": _safe_int(item.get("buyoutsCount") or item.get("buyouts")),
                "buyouts_sum_rub": _safe_float(item.get("buyoutsSumRub") or item.get("buyoutsSum")),
                "cancel_count": _safe_int(item.get("cancelCount") or item.get("cancels")),
                "cancel_sum_rub": _safe_float(item.get("cancelSumRub") or item.get("cancelSum")),
                "add_to_cart_conv": _safe_float(item.get("addToCartConv") or item.get("addToCartCR")),
                "cart_to_order_conv": _safe_float(item.get("cartToOrderConv") or item.get("cartToOrderCR")),
                "buyout_percent": _safe_float(item.get("buyoutPercent") or item.get("buyoutCR")),
                "add_to_wishlist": _safe_int(item.get("addToWishlist") or item.get("wishlist")),
                "currency": str(item.get("currency") or "RUB"),
                "payload": json.dumps(item, ensure_ascii=True),
            }
        )
    return rows
