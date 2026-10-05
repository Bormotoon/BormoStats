"""WB response parsers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from collectors.common.time import as_ch_datetime, parse_dt


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except TypeError, ValueError:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except TypeError, ValueError:
        return default


def _to_datetime(value: Any, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str):
        parsed = parse_dt(value)
        if parsed:
            return parsed
    return default or datetime.now(UTC)


def parse_sales(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    """Parse ``/api/v1/supplier/sales`` rows: one row per sold (``S…``) or returned (``R…``) unit.

    ``price_rub`` is the seller's price after the seller's discount (``priceWithDisc``, the
    same basis as Ozon's ``seller_price``), always positive; ``payout_rub`` is ``forPay``,
    the amount due for the unit before logistics, negative for a return.
    """
    rows: list[dict[str, Any]] = []
    for item in records:
        last_change = _to_datetime(item.get("lastChangeDate") or item.get("lastChangeDt"))
        event_ts = _to_datetime(item.get("date"), default=last_change)
        # the method has no quantity field: every row is one unit
        quantity = _safe_int(item.get("quantity") or item.get("saleQty") or 1, 1)
        sale_id = str(item.get("saleID") or "")
        price = _safe_float(item.get("priceWithDisc") or item.get("totalPrice"))
        payout = _safe_float(item.get("forPay"))
        is_return = (
            1
            if sale_id.upper().startswith("R")
            or quantity < 0
            or price < 0
            or payout < 0
            or "возврат" in str(item.get("supplierOperName", "")).lower()
            else 0
        )
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "srid": str(item.get("srid") or item.get("saleID") or item.get("gNumber") or ""),
                "sale_id": sale_id,
                "last_change_ts": as_ch_datetime(last_change),
                "event_ts": as_ch_datetime(event_ts),
                "nm_id": _safe_int(item.get("nmId")),
                "chrt_id": _safe_int(item.get("chrtId")),
                "barcode": item.get("barcode"),
                "quantity": abs(quantity),
                "price_rub": abs(price),
                "payout_rub": -abs(payout) if is_return else payout,
                "is_return": is_return,
                "payload": json.dumps(item, ensure_ascii=True),
            }
        )
    return rows


def parse_orders(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
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
                # seller's price after the seller's discount, as for sales; totalPrice is
                # the list price before any discount
                "price_rub": _safe_float(
                    item.get("priceWithDisc") or item.get("totalPrice") or item.get("price")
                ),
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
    """Parse ``/api/analytics/v1/stocks-report/wb-warehouses`` records.

    The table keeps one row per size (``chrt_id``), so warehouses are summed. WB reports
    a single aggregated warehouse ``-999999`` for now, which has no real id and is NULL.
    """
    snap = as_ch_datetime(snapshot_ts)
    grouped: dict[int, dict[str, Any]] = {}
    for item in records:
        chrt_id = _safe_int(item.get("chrtId"))
        warehouse_id = _safe_int(item.get("warehouseId"))
        row = grouped.get(chrt_id)
        if row is None:
            row = grouped[chrt_id] = {
                "run_id": run_id,
                "account_id": account_id,
                "snapshot_ts": snap,
                "nm_id": _safe_int(item.get("nmId")) or None,
                "chrt_id": chrt_id,
                # the report has no barcode
                "sku": None,
                "warehouse_id": warehouse_id if warehouse_id > 0 else None,
                "amount": 0,
                "parts": [],
            }
        elif row["warehouse_id"] != warehouse_id:
            row["warehouse_id"] = None
        # quantity is what customers can put into the cart right now
        row["amount"] += _safe_int(item.get("quantity"))
        row["parts"].append(item)

    rows: list[dict[str, Any]] = []
    for row in grouped.values():
        row["payload"] = json.dumps(row.pop("parts"), ensure_ascii=True)
        rows.append(row)
    return rows


def _flatten_funnel_v3(item: dict[str, Any]) -> dict[str, Any]:
    """Map a v3 sales-funnel product record onto the flat field names used below.

    ``past``/``comparison`` duplicate other days, so only ``product`` and
    ``statistic.selected`` are kept in the stored payload.
    """
    product = item.get("product") or {}
    selected = (item.get("statistic") or {}).get("selected") or {}
    conversions = selected.get("conversions") or {}
    return {
        "day": (selected.get("period") or {}).get("start"),
        "nmId": product.get("nmId"),
        "openCardCount": selected.get("openCount"),
        "addToCartCount": selected.get("cartCount"),
        "ordersCount": selected.get("orderCount"),
        "ordersSumRub": selected.get("orderSum"),
        "buyoutsCount": selected.get("buyoutCount"),
        "buyoutsSumRub": selected.get("buyoutSum"),
        "cancelCount": selected.get("cancelCount"),
        "cancelSumRub": selected.get("cancelSum"),
        "addToCartConv": conversions.get("addToCartPercent"),
        "cartToOrderConv": conversions.get("cartToOrderPercent"),
        "buyoutPercent": conversions.get("buyoutPercent"),
        "addToWishlist": selected.get("addToWishlist"),
        "currency": item.get("currency"),
        "_payload": {"product": product, "selected": selected, "currency": item.get("currency")},
    }


def parse_funnel(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        item = _flatten_funnel_v3(record) if "statistic" in record else record
        day_raw = item.get("date") or item.get("day")
        day_val = _to_datetime(day_raw).date()
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "day": day_val,
                "nm_id": _safe_int(item.get("nmId") or item.get("nm_id")),
                "open_card_count": _safe_int(item.get("openCardCount") or item.get("views")),
                "add_to_cart_count": _safe_int(
                    item.get("addToCartCount") or item.get("addsToCart")
                ),
                "orders_count": _safe_int(item.get("ordersCount") or item.get("orders")),
                "orders_sum_rub": _safe_float(
                    item.get("ordersSumRub") or item.get("ordersSum") or item.get("ordersRevenue")
                ),
                "buyouts_count": _safe_int(item.get("buyoutsCount") or item.get("buyouts")),
                "buyouts_sum_rub": _safe_float(item.get("buyoutsSumRub") or item.get("buyoutsSum")),
                "cancel_count": _safe_int(item.get("cancelCount") or item.get("cancels")),
                "cancel_sum_rub": _safe_float(item.get("cancelSumRub") or item.get("cancelSum")),
                "add_to_cart_conv": _safe_float(
                    item.get("addToCartConv") or item.get("addToCartCR")
                ),
                "cart_to_order_conv": _safe_float(
                    item.get("cartToOrderConv") or item.get("cartToOrderCR")
                ),
                "buyout_percent": _safe_float(item.get("buyoutPercent") or item.get("buyoutCR")),
                "add_to_wishlist": _safe_int(item.get("addToWishlist") or item.get("wishlist")),
                "currency": str(item.get("currency") or "RUB"),
                "payload": json.dumps(item.get("_payload", item), ensure_ascii=True),
            }
        )
    return rows


def build_wb_products(
    cards: list[dict[str, Any]], prices: list[dict[str, Any]] | None
) -> dict[str, dict[str, Any]]:
    """One document per card: the Content API card plus its Prices API entry.

    ``prices=None`` means the price source was not read this run; the ``price`` section is
    then left out so the history store carries the previous one over instead of recording
    a removal. With prices read, a card the list does not mention gets ``price: None``.
    """
    price_by_nm: dict[str, dict[str, Any]] = {}
    for entry in prices or []:
        nm_id = entry.get("nmID")
        if nm_id is not None:
            price_by_nm[str(nm_id)] = entry

    documents: dict[str, dict[str, Any]] = {}
    for card in cards:
        nm_id = card.get("nmID")
        if nm_id is None:
            continue
        key = str(nm_id)
        document: dict[str, Any] = {"card": card}
        if prices is not None:
            document["price"] = price_by_nm.get(key)
        documents[key] = document
    return documents


def parse_sales_report_lines(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    """Realization report lines, each split into the finance categories (common.finance).

    Per line, with ``sign`` = -1 for a return document:
      sales/returns  sign x retailPriceWithDisc x quantity (the seller's price)
      acquiring      -sign x acquiringFee
      commission     sign x forPay - sales/returns - acquiring (what WB kept of the price)
      logistics      -deliveryService; storage -paidStorage; acceptance -paidAcceptance
      penalties      -penalty; other -deduction + additionalPayment
    so the categories add up to ``net_accrued`` = sign x forPay - deliveryService -
    paidStorage - paidAcceptance - deduction - penalty + additionalPayment, WB's
    "Итого к оплате" (bankPaymentSum of the reports).
    """
    rows: list[dict[str, Any]] = []
    for item in records:
        rrd_id = _safe_int(item.get("rrdId"))
        day = _to_datetime(item.get("rrDate")).date() if item.get("rrDate") else None
        if not rrd_id or day is None:
            continue
        doc_type = str(item.get("docTypeName") or "")
        sign = -1.0 if doc_type == "Возврат" else 1.0
        quantity = _safe_int(item.get("quantity"))
        goods = _safe_float(item.get("retailPriceWithDisc")) * quantity if doc_type else 0.0
        for_pay = sign * _safe_float(item.get("forPay"))
        acquiring = -sign * _safe_float(item.get("acquiringFee"))
        amounts = {
            "sales": goods if sign > 0 else 0.0,
            "returns": -goods if sign < 0 else 0.0,
            "acquiring": acquiring,
            "commission": for_pay - sign * goods - acquiring,
            "logistics": -_safe_float(item.get("deliveryService")),
            "reverse_logistics": 0.0,
            "storage": -_safe_float(item.get("paidStorage")),
            "acceptance": -_safe_float(item.get("paidAcceptance")),
            "penalties": -_safe_float(item.get("penalty")),
            "other": -_safe_float(item.get("deduction"))
            + _safe_float(item.get("additionalPayment")),
        }
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "rrd_id": rrd_id,
                "report_id": _safe_int(item.get("reportId")),
                "report_type": _safe_int(item.get("reportType")),
                "day": day,
                "nm_id": _safe_int(item.get("nmId")),
                "doc_type": doc_type,
                "oper_name": str(item.get("sellerOperName") or ""),
                "quantity": quantity,
                **{name: round(value, 2) for name, value in amounts.items()},
                "net_accrued": round(sum(amounts.values()), 2),
                "payload": json.dumps(item, ensure_ascii=True),
            }
        )
    return rows
