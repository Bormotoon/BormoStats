"""Browser plugin API endpoints."""

from __future__ import annotations

import clickhouse_connect
from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import get_ch_client
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/plugin", tags=["plugin"], responses=API_ERROR_RESPONSES)


@router.get("/product/{marketplace}/{product_id}")
def product_overlay(
    marketplace: str,
    product_id: int,
    client: clickhouse_connect.driver.Client = Depends(get_ch_client),
) -> dict[str, object]:
    """Return competitor product data for browser plugin overlay."""
    product = client.query(
        "SELECT name, brand, category_name, supplier_name, rating, review_count"
        " FROM raw_competitor_products FINAL"
        " WHERE marketplace = %(marketplace)s AND product_id = %(product_id)s",
        parameters={"marketplace": marketplace, "product_id": product_id},
    )
    if not product.result_rows:
        raise HTTPException(status_code=404, detail="product_not_tracked")

    row = product.result_rows[0]
    name, brand, category, supplier, rating, reviews = row

    prices = client.query(
        "SELECT price_rub, price_old_rub, sale_percent, in_stock, snapshot_ts"
        " FROM raw_competitor_prices"
        " WHERE marketplace = %(marketplace)s AND product_id = %(product_id)s"
        " ORDER BY snapshot_ts DESC LIMIT 10",
        parameters={"marketplace": marketplace, "product_id": product_id},
    )

    price_history = [
        {
            "price_rub": float(r[0]),
            "price_old_rub": float(r[1]),
            "sale_percent": r[2],
            "in_stock": r[3],
            "snapshot_ts": str(r[4]),
        }
        for r in prices.result_rows
    ]

    positions = client.query(
        "SELECT query, position, price_rub, snapshot_ts"
        " FROM raw_competitor_search"
        " WHERE marketplace = %(marketplace)s AND product_id = %(product_id)s"
        " ORDER BY snapshot_ts DESC LIMIT 20",
        parameters={"marketplace": marketplace, "product_id": product_id},
    )

    search_positions = [
        {
            "query": r[0],
            "position": r[1],
            "price_rub": float(r[2]),
            "snapshot_ts": str(r[3]),
        }
        for r in positions.result_rows
    ]

    return {
        "product_id": product_id,
        "marketplace": marketplace,
        "name": name,
        "brand": brand,
        "category_name": category,
        "supplier_name": supplier,
        "rating": float(rating or 0),
        "review_count": reviews or 0,
        "price_history": price_history,
        "search_positions": search_positions,
    }
