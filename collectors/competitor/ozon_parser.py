"""Parser for Ozon public API responses."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


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


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        return str(value)
    except TypeError, ValueError:
        return default


def _dig(data: dict[str, Any] | None, *keys: str) -> Any:
    """Deep dictionary key lookup."""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def parse_ozon_product_cards(
    records: list[dict[str, Any]],
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse Ozon composer API responses into product info and price rows.

    Returns (product_rows, price_rows) compatible with raw_competitor_*
    tables (marketplace = 'ozon').
    """
    now = datetime.now(UTC)
    product_rows: list[dict[str, Any]] = []
    price_rows: list[dict[str, Any]] = []

    for state in records:
        widget_state = _dig(state, "widgetStates")
        if not isinstance(widget_state, dict):
            continue

        product_id = 0
        name = ""
        brand = ""
        category_name = ""
        rating = 0.0
        review_count = 0
        price = 0.0
        price_old = 0.0
        stock = 0

        for key, raw in widget_state.items():
            if not isinstance(raw, str):
                continue
            try:
                payload: dict[str, Any] = json.loads(raw)
            except TypeError, ValueError:
                continue

            if "webProductHeading" in key:
                name = _safe_str(_dig(payload, "name"))
                brand = _safe_str(_dig(payload, "brandName"))
                product_id = _safe_int(_dig(payload, "id"))

            elif "webPrice" in key:
                price = _safe_float(_dig(payload, "price")) / 100.0
                price_old = _safe_float(_dig(payload, "originalPrice")) / 100.0

            elif "webStock" in key:
                stock = _safe_int(_dig(payload, "stock"))

            elif "webRating" in key:
                rating = float(_dig(payload, "rating") or 0)
                review_count = _safe_int(_dig(payload, "reviewCount"))

            elif "webCategoryHeader" in key:
                cat = _dig(payload, "category")
                category_name = _safe_str(cat.get("name") if isinstance(cat, dict) else None)

        if not product_id:
            continue

        product_rows.append(
            {
                "run_id": run_id,
                "marketplace": "ozon",
                "product_id": product_id,
                "name": name,
                "brand": brand,
                "category_id": 0,
                "category_name": category_name,
                "supplier_id": 0,
                "supplier_name": "",
                "rating": rating,
                "review_count": review_count,
                "payload": json.dumps(state, ensure_ascii=True),
                "updated_at": now,
            }
        )

        price_rows.append(
            {
                "run_id": run_id,
                "marketplace": "ozon",
                "product_id": product_id,
                "price_rub": price,
                "price_old_rub": price_old,
                "sale_percent": 0,
                "in_stock": stock,
                "snapshot_ts": now,
                "payload": json.dumps(
                    {"price": price, "price_old": price_old, "stock": stock},
                    ensure_ascii=True,
                ),
            }
        )

    return product_rows, price_rows
