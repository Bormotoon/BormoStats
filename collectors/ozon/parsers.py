"""Ozon response parsers.

Field names follow the Seller API / Performance API specs of the methods in
``collectors.ozon.endpoints``; Ozon SKU is used as ``ozon_product_id`` everywhere
because postings, accruals and stocks all identify goods by SKU.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
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


def _money(value: Any) -> float:
    """Ozon money objects are ``{"amount": "-42.70", "currency": "RUB"}``."""
    if isinstance(value, dict):
        return _safe_float(value.get("amount"))
    return _safe_float(value)


def _money_currency(value: Any, default: str = "RUB") -> str:
    if isinstance(value, dict) and value.get("currency"):
        return str(value["currency"])
    return default


def _report_number(value: Any) -> float:
    """Performance API reports may render numbers as ``"1 234,56"``."""
    if isinstance(value, str):
        value = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    return _safe_float(value)


def _to_datetime(value: Any, default: datetime | None = None) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            return parse_dt(value)
        except ValueError:
            return default
    return default


def _to_day(value: Any) -> date | None:
    if isinstance(value, str) and len(value) == 10 and value[2] == "." and value[5] == ".":
        # Performance reports use DD.MM.YYYY
        try:
            return datetime.strptime(value, "%d.%m.%Y").date()
        except ValueError:
            return None
    parsed = _to_datetime(value)
    return parsed.date() if parsed else None


def _posting_warehouse_id(posting: dict[str, Any]) -> int | None:
    delivery_method = posting.get("delivery_method")
    analytics = posting.get("analytics_data")
    for source in (delivery_method, analytics):
        if isinstance(source, dict):
            warehouse_id = _safe_int(source.get("warehouse_id"))
            if warehouse_id:
                return warehouse_id
    return None


def _financial_products_by_sku(posting: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    financial = posting.get("financial_data")
    products = financial.get("products") if isinstance(financial, dict) else None
    by_sku: dict[int, list[dict[str, Any]]] = {}
    if isinstance(products, list):
        for product in products:
            if isinstance(product, dict):
                # financial_data names the SKU ``product_id``
                by_sku.setdefault(_safe_int(product.get("product_id")), []).append(product)
    return by_sku


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
        # delivering_date is when the posting was handed over to delivery
        shipped_at = _to_datetime(posting.get("delivering_date"))

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
                # the posting lists expose no delivery or cancellation timestamps
                "delivered_at": None,
                "canceled_at": None,
                "ozon_warehouse_id": _posting_warehouse_id(posting),
                "payload": json.dumps(posting, ensure_ascii=True),
            }
        )

        products = posting.get("products")
        if not isinstance(products, list):
            continue

        financial_by_sku = _financial_products_by_sku(posting)
        for product in products:
            if not isinstance(product, dict):
                continue
            sku = _safe_int(product.get("sku"))
            price = _money(product.get("price"))
            financial_matches = financial_by_sku.get(sku) or []
            financial = financial_matches.pop(0) if financial_matches else {}
            payout = financial.get("payout")
            items_rows.append(
                {
                    "run_id": run_id,
                    "account_id": account_id,
                    "posting_number": posting_number,
                    "ozon_product_id": sku,
                    "offer_id": product.get("offer_id"),
                    "name": product.get("name"),
                    "quantity": max(1, _safe_int(product.get("quantity"), 1)),
                    "price": price,
                    "payout": _safe_float(payout) if payout is not None else price,
                    "payload": json.dumps(
                        {"product": product, "financial": financial}, ensure_ascii=True
                    ),
                }
            )

    return postings_rows, items_rows


def parse_stocks(
    records: list[dict[str, Any]],
    run_id: str,
    account_id: str,
    snapshot_ts: datetime,
) -> list[dict[str, Any]]:
    """Parse ``/v4/product/info/stocks`` items and ``/v1/analytics/stocks`` FBO rows.

    Rows are summed per (SKU, warehouse) because that is the table's dedup key; a v4
    stock spread over several warehouses has no single warehouse and is stored as NULL.
    """
    snap = as_ch_datetime(snapshot_ts)
    has_fbo_analytics = any("available_stock_count" in item for item in records)
    grouped: dict[tuple[int, int | None], dict[str, Any]] = {}

    def add(
        sku: int,
        offer_id: Any,
        warehouse_id: int | None,
        present: int,
        reserved: int,
        part: dict[str, Any],
    ) -> None:
        row = grouped.get((sku, warehouse_id))
        if row is None:
            row = grouped[(sku, warehouse_id)] = {
                "run_id": run_id,
                "account_id": account_id,
                "snapshot_ts": snap,
                "ozon_product_id": sku,
                "offer_id": offer_id,
                "warehouse_id": warehouse_id,
                "present": 0,
                "reserved": 0,
                "parts": [],
            }
        row["present"] += present
        row["reserved"] += reserved
        row["parts"].append(part)

    for item in records:
        if "available_stock_count" in item:
            add(
                _safe_int(item.get("sku")),
                item.get("offer_id"),
                _safe_int(item.get("warehouse_id")) or None,
                _safe_int(item.get("available_stock_count")),
                0,
                {"type": "fbo", **item},
            )
            continue

        stocks = item.get("stocks")
        if not isinstance(stocks, list):
            continue
        for stock in stocks:
            if not isinstance(stock, dict):
                continue
            if has_fbo_analytics and str(stock.get("type") or "").lower() == "fbo":
                continue
            warehouse_ids = stock.get("warehouse_ids")
            warehouse_id = (
                _safe_int(warehouse_ids[0]) or None
                if isinstance(warehouse_ids, list) and len(warehouse_ids) == 1
                else None
            )
            add(
                _safe_int(stock.get("sku")) or _safe_int(item.get("product_id")),
                item.get("offer_id"),
                warehouse_id,
                _safe_int(stock.get("present")),
                _safe_int(stock.get("reserved")),
                {"product_id": item.get("product_id"), **stock},
            )

    rows: list[dict[str, Any]] = []
    for row in grouped.values():
        parts = row.pop("parts")
        row["payload"] = json.dumps(parts, ensure_ascii=True)
        rows.append(row)
    return rows


def parse_ads_daily(
    records: list[dict[str, Any]],
    run_id: str,
    account_id: str,
) -> list[dict[str, Any]]:
    """Parse ``/api/client/statistics/daily/json`` rows."""
    rows: list[dict[str, Any]] = []
    for item in records:
        day = _to_day(item.get("date"))
        if day is None:
            continue
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "day": day,
                "campaign_id": str(item.get("id") or "unknown"),
                "impressions": int(_report_number(item.get("views"))),
                "clicks": int(_report_number(item.get("clicks"))),
                "cost": _report_number(item.get("moneySpent")),
                "orders": int(_report_number(item.get("orders"))),
                "revenue": _report_number(item.get("ordersMoney")),
                "payload": json.dumps(item, ensure_ascii=True),
            }
        )
    return rows


def _fee_type_ids(accrual: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    non_item = accrual.get("non_item_fee")
    if isinstance(non_item, dict) and non_item.get("type_id") is not None:
        ids.append(_safe_int(non_item.get("type_id")))
    item_fees = accrual.get("item_fees")
    if isinstance(item_fees, dict):
        for sku_fees in item_fees.get("fees") or []:
            if isinstance(sku_fees, dict):
                ids.extend(
                    _safe_int(fee.get("type_id"))
                    for fee in sku_fees.get("fees") or []
                    if isinstance(fee, dict)
                )
    container = accrual.get("container_fees")
    if isinstance(container, dict):
        ids.extend(
            _safe_int(fee.get("type_id"))
            for fee in container.get("fees") or []
            if isinstance(fee, dict)
        )
    return ids


def accrual_operation_type(accrual: dict[str, Any], type_names: dict[int, str]) -> str:
    """Label an accrual for ``stg_finance_ops.type``.

    Fee accruals take the dictionary name of their single fee type (``PayPerClick``,
    ``Acquiring``); posting accruals combine sale, commission and delivery services
    and are labelled ``posting``.
    """
    category = str(accrual.get("accrued_category") or "UNSPECIFIED").lower()
    if category == "posting":
        return "posting"
    type_ids = set(_fee_type_ids(accrual))
    if len(type_ids) == 1:
        type_id = type_ids.pop()
        return type_names.get(type_id) or f"accrual_type_{type_id}"
    return category


def parse_finance_accruals(
    records: list[dict[str, Any]],
    run_id: str,
    account_id: str,
    type_names: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Parse ``/v1/finance/accrual/by-day`` accruals, one row per ``accrual_id``.

    ``total_amount`` is the signed total of the accrual, so the rows add up to the
    seller's balance without double counting the nested breakdown kept in ``payload``.
    """
    names = type_names or {}
    rows: list[dict[str, Any]] = []
    for accrual in records:
        accrual_id = accrual.get("accrual_id")
        operation_day = _to_day(accrual.get("date"))
        if accrual_id is None or operation_day is None:
            continue
        total = accrual.get("total_amount")
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "operation_id": str(accrual_id),
                "operation_ts": datetime.combine(operation_day, datetime.min.time()),
                "type": accrual_operation_type(accrual, names),
                "amount": _money(total),
                "currency": _money_currency(total),
                "source": "accrual_by_day",
                "payload": json.dumps(accrual, ensure_ascii=True),
            }
        )
    return rows


def build_ozon_products(
    product_ids: list[int],
    info: list[dict[str, Any]],
    attributes: list[dict[str, Any]] | None,
    prices: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """One document per product from the three catalogue methods.

    ``attributes``/``prices`` set to ``None`` mean that source was not read this run; the
    section is left out so the history store carries the previous one over.
    """

    def by_id(items: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
        return {str(item[field]): item for item in items if item.get(field) is not None}

    info_by_id = by_id(info, "id")
    attributes_by_id = by_id(attributes or [], "id")
    prices_by_id = by_id(prices or [], "product_id")

    documents: dict[str, dict[str, Any]] = {}
    for product_id in product_ids:
        key = str(product_id)
        document: dict[str, Any] = {"info": info_by_id.get(key)}
        if attributes is not None:
            document["attributes"] = attributes_by_id.get(key)
        if prices is not None:
            document["price"] = prices_by_id.get(key)
        documents[key] = document
    return documents
