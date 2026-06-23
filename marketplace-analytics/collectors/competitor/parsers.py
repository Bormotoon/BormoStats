"""Parsers for WB public API responses."""

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


def parse_wb_product_cards(
    records: list[dict[str, Any]],
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse WB card detail API response into product info and price rows.

    Returns (product_rows, price_rows).
    """
    now = datetime.now(UTC)
    product_rows: list[dict[str, Any]] = []
    price_rows: list[dict[str, Any]] = []

    for item in records:
        product_id = _safe_int(item.get("id"))
        if not product_id:
            continue

        name = _safe_str(item.get("name"))
        brand = _safe_str(item.get("brand"))
        category_id = _safe_int(item.get("subjectId") or item.get("subject_id"))
        category_name = _safe_str(item.get("subject") or item.get("subject_name"))
        supplier_id = _safe_int(item.get("supplierId") or item.get("supplier_id"))
        supplier_name = _safe_str(item.get("supplierName") or item.get("supplier_name"))
        rating = float(item.get("rating", 0) or 0)
        review_count = _safe_int(item.get("feedbacks") or item.get("reviews"))

        product_rows.append(
            {
                "run_id": run_id,
                "marketplace": "wb",
                "product_id": product_id,
                "name": name,
                "brand": brand,
                "category_id": category_id,
                "category_name": category_name,
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "rating": rating,
                "review_count": review_count,
                "payload": json.dumps(item, ensure_ascii=True),
                "updated_at": now,
            }
        )

        sizes = item.get("sizes")
        if not isinstance(sizes, list):
            continue

        for size in sizes:
            price = _safe_float(size.get("totalPrice") or size.get("price") or 0.0)
            price_old = _safe_float(size.get("origPrice") or size.get("originalPrice") or 0.0)
            sale = _safe_int(size.get("sale") or 0)
            stock = _safe_int(size.get("qty") or size.get("quantity") or 0)

            price_rows.append(
                {
                    "run_id": run_id,
                    "marketplace": "wb",
                    "product_id": product_id,
                    "price_rub": price / 100.0 if price > 100 else price,
                    "price_old_rub": price_old / 100.0 if price_old > 100 else price_old,
                    "sale_percent": sale,
                    "in_stock": stock,
                    "snapshot_ts": now,
                    "payload": json.dumps(size, ensure_ascii=True),
                }
            )

    return product_rows, price_rows
