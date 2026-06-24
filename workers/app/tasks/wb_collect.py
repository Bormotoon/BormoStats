"""WB collection tasks."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from app.utils.celery_helpers import shared_task
from app.utils.chunking import date_chunks
from app.utils.collection import (
    collect_backfill,
    collect_incremental,
    collect_snapshot,
    insert_rows,
    wrap_task,
)
from app.utils.locking import LockNotAcquiredError, lock_scope
from app.utils.metrics import observe_empty_payload
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context

from collectors.wb.client import WbApiClient
from collectors.wb.parsers import parse_funnel, parse_orders, parse_sales, parse_stocks

WB_ACCOUNT_ID = os.getenv("WB_ACCOUNT_ID", "default")

RAW_WB_SALES_COLUMNS = [
    "run_id",
    "account_id",
    "srid",
    "last_change_ts",
    "event_ts",
    "nm_id",
    "chrt_id",
    "barcode",
    "quantity",
    "price_rub",
    "payout_rub",
    "is_return",
    "payload",
]

RAW_WB_ORDERS_COLUMNS = [
    "run_id",
    "account_id",
    "srid",
    "last_change_ts",
    "event_ts",
    "nm_id",
    "chrt_id",
    "quantity",
    "price_rub",
    "payload",
]

RAW_WB_STOCKS_COLUMNS = [
    "run_id",
    "account_id",
    "snapshot_ts",
    "nm_id",
    "chrt_id",
    "sku",
    "warehouse_id",
    "amount",
    "payload",
]

RAW_WB_FUNNEL_COLUMNS = [
    "run_id",
    "account_id",
    "day",
    "nm_id",
    "open_card_count",
    "add_to_cart_count",
    "orders_count",
    "orders_sum_rub",
    "buyouts_count",
    "buyouts_sum_rub",
    "cancel_count",
    "cancel_sum_rub",
    "add_to_cart_conv",
    "cart_to_order_conv",
    "buyout_percent",
    "add_to_wishlist",
    "currency",
    "payload",
]


def _wb_client() -> WbApiClient | None:
    statistics_token = os.getenv("WB_TOKEN_STATISTICS", "")
    analytics_token = os.getenv("WB_TOKEN_ANALYTICS", "")
    if not statistics_token or not analytics_token:
        return None
    return WbApiClient(statistics_token=statistics_token, analytics_token=analytics_token)


# -- Sales tasks --


@shared_task(name="tasks.wb_collect.wb_sales_incremental")
def wb_sales_incremental(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    def fetch(watermark: datetime) -> list[dict[str, Any]]:
        return wb.sales_since(watermark)

    return wrap_task(
        collect_incremental,
        task_name="tasks.wb_collect.wb_sales_incremental",
        source="wb_sales",
        account_id=account_id,
        fetch_fn=fetch,
        parse_fn=parse_sales,
        columns=RAW_WB_SALES_COLUMNS,
        table="raw_wb_sales",
    )


@shared_task(name="tasks.wb_collect.wb_sales_backfill_days")
def wb_sales_backfill_days(days: int = 14, account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    def fetch(day_cursor: datetime) -> list[dict[str, Any]]:
        return wb.sales_for_day(day_cursor.date())

    return collect_backfill(
        task_name="tasks.wb_collect.wb_sales_backfill_days",
        source="wb_sales",
        account_id=account_id,
        days=days,
        max_days=90,
        fetch_day_fn=fetch,
        parse_fn=parse_sales,
        columns=RAW_WB_SALES_COLUMNS,
        table="raw_wb_sales",
    )


# -- Orders tasks --


@shared_task(name="tasks.wb_collect.wb_orders_incremental")
def wb_orders_incremental(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    def fetch(watermark: datetime) -> list[dict[str, Any]]:
        return wb.orders_since(watermark)

    return wrap_task(
        collect_incremental,
        task_name="tasks.wb_collect.wb_orders_incremental",
        source="wb_orders",
        account_id=account_id,
        fetch_fn=fetch,
        parse_fn=parse_orders,
        columns=RAW_WB_ORDERS_COLUMNS,
        table="raw_wb_orders",
    )


@shared_task(name="tasks.wb_collect.wb_orders_backfill_days")
def wb_orders_backfill_days(days: int = 14, account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    def fetch(day_cursor: datetime) -> list[dict[str, Any]]:
        return wb.orders_for_day(day_cursor.date())

    return collect_backfill(
        task_name="tasks.wb_collect.wb_orders_backfill_days",
        source="wb_orders",
        account_id=account_id,
        days=days,
        max_days=90,
        fetch_day_fn=fetch,
        parse_fn=parse_orders,
        columns=RAW_WB_ORDERS_COLUMNS,
        table="raw_wb_orders",
    )


# -- Stocks tasks --


@shared_task(name="tasks.wb_collect.wb_stocks_snapshot")
def wb_stocks_snapshot(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    def fetch() -> list[dict[str, Any]]:
        return wb.stocks()

    return collect_snapshot(
        task_name="tasks.wb_collect.wb_stocks_snapshot",
        source="wb_stocks",
        account_id=account_id,
        fetch_fn=fetch,
        parse_fn=parse_stocks,
        columns=RAW_WB_STOCKS_COLUMNS,
        table="raw_wb_stocks",
    )


# -- Funnel tasks --


@shared_task(name="tasks.wb_collect.wb_funnel_roll")
def wb_funnel_roll(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    task_name = "tasks.wb_collect.wb_funnel_roll"
    run_id, started_at = new_run_context()
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    to_day = datetime.now(UTC).date()
    from_day = to_day - timedelta(days=7)

    redis_client = get_redis_client()
    try:
        with lock_scope(
            redis_client=redis_client,
            source="wb_funnel",
            account_id=account_id,
            ttl_seconds=1200,
            auto_renew=True,
        ) as lock:
            ch_client = get_ch_client()
            try:
                inserted = 0
                for chunk_from, chunk_to in date_chunks(from_day, to_day, chunk_days=3):
                    lock.ensure_held()
                    records = wb.funnel_daily(from_day=chunk_from, to_day=chunk_to)
                    rows = parse_funnel(records, run_id=run_id, account_id=account_id)
                    if not rows:
                        observe_empty_payload("wb_funnel")
                    inserted += insert_rows(
                        ch_client,
                        "raw_wb_funnel_daily",
                        RAW_WB_FUNNEL_COLUMNS,
                        rows,
                    )
                log_task_run(
                    ch_client,
                    task_name,
                    run_id,
                    started_at,
                    "success",
                    inserted,
                    "wb funnel hourly roll (7-day window)",
                )
                return {"status": "success", "rows": inserted}
            except Exception as exc:
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.wb_collect.wb_funnel_backfill_days")
def wb_funnel_backfill_days(days: int = 14, account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    safe_days = max(1, min(days, 365))
    task_name = "tasks.wb_collect.wb_funnel_backfill_days"
    run_id, started_at = new_run_context()
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    now_day = datetime.now(UTC).date()
    start_day = now_day - timedelta(days=safe_days)
    total_rows = 0
    ch_client = get_ch_client()
    redis_client = get_redis_client()
    try:
        with lock_scope(
            redis_client=redis_client,
            source="wb_funnel",
            account_id=account_id,
            ttl_seconds=1200,
            auto_renew=True,
        ) as lock:
            for chunk_from, chunk_to in date_chunks(start_day, now_day, chunk_days=3):
                lock.ensure_held()
                records = wb.funnel_daily(from_day=chunk_from, to_day=chunk_to)
                rows = parse_funnel(records, run_id=run_id, account_id=account_id)
                if not rows:
                    observe_empty_payload("wb_funnel")
                total_rows += insert_rows(
                    ch_client,
                    "raw_wb_funnel_daily",
                    RAW_WB_FUNNEL_COLUMNS,
                    rows,
                )

            log_task_run(
                ch_client,
                task_name,
                run_id,
                started_at,
                "success",
                total_rows,
                f"wb funnel backfill {safe_days} days",
            )
            return {"status": "success", "rows": total_rows, "days": safe_days}
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}
    except Exception as exc:
        log_task_run(ch_client, task_name, run_id, started_at, "failed", total_rows, str(exc))
        raise
