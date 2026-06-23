"""Competitor product data collection and mart build tasks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.sql.loader import load_sql
from app.utils.celery_helpers import shared_task
from app.utils.collection import insert_rows
from app.utils.runtime import get_ch_client, log_task_run, new_run_context

from collectors.competitor.client import WbPublicApiClient
from collectors.competitor.ozon_client import OzonPublicApiClient
from collectors.competitor.ozon_parser import parse_ozon_product_cards
from collectors.competitor.parsers import parse_wb_product_cards, parse_wb_search_results

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

RAW_COMPETITOR_SEARCH_COLUMNS = [
    "run_id",
    "marketplace",
    "query",
    "search_page",
    "position",
    "product_id",
    "price_rub",
    "snapshot_ts",
    "ingested_at",
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


def _load_tracked_ozon_ids(ch_client: Any) -> list[int]:
    """Load tracked Ozon product IDs from dim_product and env override."""
    seen: set[int] = set()
    try:
        rows = ch_client.query(
            "SELECT DISTINCT product_id FROM dim_product FINAL WHERE marketplace = 'ozon'"
        )
        for row in rows.result_rows:
            val = row[0]
            if val is not None and val > 0:
                seen.add(int(val))
    except Exception:
        pass
    override = os.getenv("COMPETITOR_TRACKED_OZON_IDS", "")
    if override:
        for part in override.split(","):
            part = part.strip()
            if part:
                try:
                    pid = int(part)
                    if pid > 0:
                        seen.add(pid)
                except TypeError, ValueError:
                    pass
    return sorted(seen)


def _load_tracked_keywords() -> list[str]:
    """Load tracked search keywords from env."""
    raw = os.getenv("COMPETITOR_TRACKED_KEYWORDS", "")
    if not raw:
        return []
    return [kw.strip() for kw in raw.split(",") if kw.strip()]


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


@shared_task(name="tasks.competitor_collect.wb_search_results")
def wb_search_results() -> dict[str, object]:
    """Search WB catalog for tracked keywords and store results."""
    run_id, started_at = new_run_context()
    ch_client = get_ch_client()
    keywords = _load_tracked_keywords()

    if not keywords:
        return {"status": "skipped", "reason": "no_tracked_keywords"}

    client = WbPublicApiClient()
    total = 0
    try:
        for keyword in keywords:
            raw_results = client.search(keyword)
            search_rows = parse_wb_search_results(raw_results, run_id, keyword, 1)
            if search_rows:
                total += insert_rows(
                    ch_client,
                    "raw_competitor_search",
                    RAW_COMPETITOR_SEARCH_COLUMNS,
                    search_rows,
                )

        log_task_run(
            ch_client,
            "tasks.competitor_collect.wb_search_results",
            run_id,
            started_at,
            "success",
            total,
            f"keywords={len(keywords)} rows={total}",
        )
        return {"status": "success", "rows": total}
    finally:
        client.close()


_MARTS_DIR = Path(__file__).resolve().parents[1] / "sql" / "marts"


def _load(name: str) -> str:
    return load_sql(_MARTS_DIR, name)


@shared_task(name="tasks.competitor_collect.ozon_product_cards")
def ozon_product_cards() -> dict[str, object]:
    """Collect product card data from Ozon public API for tracked product ids."""
    run_id, started_at = new_run_context()
    ch_client = get_ch_client()
    ozon_ids = _load_tracked_ozon_ids(ch_client)

    if not ozon_ids:
        return {"status": "skipped", "reason": "no_tracked_products"}

    client = OzonPublicApiClient()
    try:
        raw_cards = client.product_cards_batch(ozon_ids)
        product_rows, price_rows = parse_ozon_product_cards(raw_cards, run_id)

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
            "tasks.competitor_collect.ozon_product_cards",
            run_id,
            started_at,
            "success",
            total,
            f"tracked={len(ozon_ids)} products={len(product_rows)} prices={len(price_rows)}",
        )
        return {"status": "success", "rows": total}
    finally:
        client.close()


@shared_task(name="tasks.competitor_collect.build_marts")
def build_marts() -> dict[str, object]:
    """Build competitor analytics marts (category daily, product daily)."""
    run_id, started_at = new_run_context()
    ch_client = get_ch_client()

    try:
        ch_client.command(
            "ALTER TABLE mrt_competitor_daily DELETE WHERE day = yesterday()",
        )
        ch_client.command(
            "ALTER TABLE mrt_competitor_category_daily DELETE WHERE day = yesterday()",
        )
        ch_client.command(
            "ALTER TABLE mrt_competitor_keyword_daily DELETE WHERE day = yesterday()",
        )

        ch_client.command(_load("mrt_competitor_daily.sql"), parameters={"days": 2})
        ch_client.command(_load("mrt_competitor_category_daily.sql"))
        ch_client.command(_load("mrt_competitor_keyword_daily.sql"))

        log_task_run(
            ch_client,
            "tasks.competitor_collect.build_marts",
            run_id,
            started_at,
            "success",
            0,
            "marts built",
        )
        return {"status": "success"}
    except Exception as exc:
        log_task_run(
            ch_client,
            "tasks.competitor_collect.build_marts",
            run_id,
            started_at,
            "failed",
            0,
            str(exc),
        )
        raise
