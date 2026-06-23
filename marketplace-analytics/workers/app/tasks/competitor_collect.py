"""Competitor product data collection tasks."""

from __future__ import annotations

import os
from typing import Any

from app.utils.celery_helpers import shared_task
from app.utils.collection import insert_rows
from app.utils.runtime import get_ch_client, log_task_run, new_run_context

from collectors.competitor.client import WbPublicApiClient
from collectors.competitor.parsers import parse_wb_product_cards

RAW_COMPETITOR_PRODUCTS_COLUMNS = [
    "run_id",
    "marketplace",
    "product_id",
    "name",
    "brand",
    "category_id",
    "category_name",
    "supplier_id",
    "supplier_name",
    "rating",
    "review_count",
    "payload",
    "updated_at",
]

RAW_COMPETITOR_PRICES_COLUMNS = [
    "run_id",
    "marketplace",
    "product_id",
    "price_rub",
    "price_old_rub",
    "sale_percent",
    "in_stock",
    "snapshot_ts",
    "payload",
]


def _load_tracked_nm_ids(ch_client: Any) -> list[int]:
    """Load tracked product nm_ids from dim_product and env override."""
    seen: set[int] = set()

    try:
        rows = ch_client.query(
            "SELECT DISTINCT product_id FROM dim_product FINAL WHERE marketplace = 'wb'"
        )
        for row in rows.result_rows:
            val = row[0]
            if val is not None and val > 0:
                seen.add(int(val))
    except Exception:
        pass

    override = os.getenv("COMPETITOR_TRACKED_NM_IDS", "")
    if override:
        for part in override.split(","):
            part = part.strip()
            if part:
                try:
                    nm_id = int(part)
                    if nm_id > 0:
                        seen.add(nm_id)
                except TypeError, ValueError:
                    pass

    return sorted(seen)


@shared_task(name="tasks.competitor_collect.wb_product_cards")
def wb_product_cards() -> dict[str, object]:
    """Collect product card data from WB public API for tracked nm_ids."""
    run_id, started_at = new_run_context()
    ch_client = get_ch_client()
    nm_ids = _load_tracked_nm_ids(ch_client)

    if not nm_ids:
        return {"status": "skipped", "reason": "no_tracked_products"}

    client = WbPublicApiClient()
    try:
        raw_cards = client.product_cards(nm_ids)
        product_rows, price_rows = parse_wb_product_cards(raw_cards, run_id)

        total = 0
        if product_rows:
            total += insert_rows(
                ch_client,
                "raw_competitor_products",
                RAW_COMPETITOR_PRODUCTS_COLUMNS,
                product_rows,
            )
        if price_rows:
            total += insert_rows(
                ch_client,
                "raw_competitor_prices",
                RAW_COMPETITOR_PRICES_COLUMNS,
                price_rows,
            )

        log_task_run(
            ch_client,
            "tasks.competitor_collect.wb_product_cards",
            run_id,
            started_at,
            "success",
            total,
            f"tracked={len(nm_ids)} products={len(product_rows)} prices={len(price_rows)}",
        )
        return {"status": "success", "rows": total}
    finally:
        client.close()
