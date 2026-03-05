"""WB collection tasks."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task

from collectors.wb.client import WbApiClient
from collectors.wb.parsers import parse_funnel, parse_orders, parse_sales, parse_stocks
from app.utils.chunking import date_chunks
from app.utils.locking import LockNotAcquired, lock_scope
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context
from app.utils.watermarks import get_watermark, set_watermark

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


def _insert_rows(client: Any, table: str, columns: list[str], rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    data = [[row.get(col) for col in columns] for row in rows]
    client.insert(table=table, data=data, column_names=columns)
    return len(rows)


def _collect_sales_incremental(account_id: str, start_from: datetime | None = None) -> dict[str, Any]:
    task_name = "tasks.wb_collect.wb_sales_incremental"
    run_id, started_at = new_run_context(task_name)
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    redis_client = get_redis_client()
    with lock_scope(redis_client=redis_client, source="wb_sales", account_id=account_id, ttl_seconds=1200):
        ch_client = get_ch_client()
        try:
            watermark = start_from or get_watermark(ch_client, "wb_sales", account_id)
            records = wb.sales_since(watermark)
            rows = parse_sales(records, run_id=run_id, account_id=account_id)
            inserted = _insert_rows(ch_client, "raw_wb_sales", RAW_WB_SALES_COLUMNS, rows)

            latest_ts = max((row["last_change_ts"] for row in rows), default=watermark.replace(tzinfo=None))
            set_watermark(ch_client, "wb_sales", account_id, latest_ts.replace(tzinfo=UTC))
            log_task_run(ch_client, task_name, run_id, started_at, "success", inserted, "wb sales collected")
            return {"status": "success", "rows": inserted, "watermark": str(latest_ts)}
        except Exception as exc:
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise
        finally:
            ch_client.close()


def _collect_orders_incremental(account_id: str, start_from: datetime | None = None) -> dict[str, Any]:
    task_name = "tasks.wb_collect.wb_orders_incremental"
    run_id, started_at = new_run_context(task_name)
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    redis_client = get_redis_client()
    with lock_scope(redis_client=redis_client, source="wb_orders", account_id=account_id, ttl_seconds=1200):
        ch_client = get_ch_client()
        try:
            watermark = start_from or get_watermark(ch_client, "wb_orders", account_id)
            records = wb.orders_since(watermark)
            rows = parse_orders(records, run_id=run_id, account_id=account_id)
            inserted = _insert_rows(ch_client, "raw_wb_orders", RAW_WB_ORDERS_COLUMNS, rows)

            latest_ts = max((row["last_change_ts"] for row in rows), default=watermark.replace(tzinfo=None))
            set_watermark(ch_client, "wb_orders", account_id, latest_ts.replace(tzinfo=UTC))
            log_task_run(ch_client, task_name, run_id, started_at, "success", inserted, "wb orders collected")
            return {"status": "success", "rows": inserted, "watermark": str(latest_ts)}
        except Exception as exc:
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise
        finally:
            ch_client.close()


@shared_task(name="tasks.wb_collect.wb_sales_incremental")
def wb_sales_incremental(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    try:
        return _collect_sales_incremental(account_id=account_id)
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.wb_collect.wb_orders_incremental")
def wb_orders_incremental(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    try:
        return _collect_orders_incremental(account_id=account_id)
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.wb_collect.wb_stocks_snapshot")
def wb_stocks_snapshot(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    task_name = "tasks.wb_collect.wb_stocks_snapshot"
    run_id, started_at = new_run_context(task_name)
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    snapshot_ts = datetime.now(UTC)
    redis_client = get_redis_client()
    try:
        with lock_scope(redis_client=redis_client, source="wb_stocks", account_id=account_id, ttl_seconds=900):
            ch_client = get_ch_client()
            try:
                records = wb.stocks()
                rows = parse_stocks(records, run_id=run_id, account_id=account_id, snapshot_ts=snapshot_ts)
                inserted = _insert_rows(ch_client, "raw_wb_stocks", RAW_WB_STOCKS_COLUMNS, rows)
                log_task_run(ch_client, task_name, run_id, started_at, "success", inserted, "wb stocks snapshot")
                return {"status": "success", "rows": inserted}
            except Exception as exc:
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
            finally:
                ch_client.close()
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.wb_collect.wb_funnel_roll")
def wb_funnel_roll(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    task_name = "tasks.wb_collect.wb_funnel_roll"
    run_id, started_at = new_run_context(task_name)
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    to_day = datetime.now(UTC).date()
    from_day = to_day - timedelta(days=7)

    redis_client = get_redis_client()
    try:
        with lock_scope(redis_client=redis_client, source="wb_funnel", account_id=account_id, ttl_seconds=1200):
            ch_client = get_ch_client()
            try:
                inserted = 0
                for chunk_from, chunk_to in date_chunks(from_day, to_day, chunk_days=3):
                    records = wb.funnel_daily(from_day=chunk_from, to_day=chunk_to)
                    rows = parse_funnel(records, run_id=run_id, account_id=account_id)
                    inserted += _insert_rows(ch_client, "raw_wb_funnel_daily", RAW_WB_FUNNEL_COLUMNS, rows)
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
            finally:
                ch_client.close()
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.wb_collect.wb_sales_backfill_days")
def wb_sales_backfill_days(days: int = 14, account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    safe_days = max(1, min(days, 90))
    task_name = "tasks.wb_collect.wb_sales_backfill_days"
    run_id, started_at = new_run_context(task_name)
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    now_day = datetime.now(UTC).date()
    start_day = now_day - timedelta(days=safe_days)
    total_rows = 0
    latest_seen_ts: datetime | None = None

    ch_client = get_ch_client()
    redis_client = get_redis_client()
    try:
        with lock_scope(redis_client=redis_client, source="wb_sales", account_id=account_id, ttl_seconds=1800):
            for day_cursor, _ in date_chunks(start_day, now_day, chunk_days=1):
                records = wb.sales_for_day(day_cursor)
                rows = parse_sales(records, run_id=run_id, account_id=account_id)
                total_rows += _insert_rows(ch_client, "raw_wb_sales", RAW_WB_SALES_COLUMNS, rows)
                if rows:
                    day_latest = max(row["last_change_ts"] for row in rows)
                    day_latest_utc = day_latest.replace(tzinfo=UTC)
                    if latest_seen_ts is None or day_latest_utc > latest_seen_ts:
                        latest_seen_ts = day_latest_utc

            if latest_seen_ts is not None:
                set_watermark(ch_client, "wb_sales", account_id, latest_seen_ts)
            log_task_run(
                ch_client,
                task_name,
                run_id,
                started_at,
                "success",
                total_rows,
                f"wb sales backfill by day ({safe_days} days)",
            )
            return {"status": "success", "rows": total_rows, "days": safe_days}
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}
    except Exception as exc:
        log_task_run(ch_client, task_name, run_id, started_at, "failed", total_rows, str(exc))
        raise
    finally:
        ch_client.close()


@shared_task(name="tasks.wb_collect.wb_orders_backfill_days")
def wb_orders_backfill_days(days: int = 14, account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    safe_days = max(1, min(days, 90))
    task_name = "tasks.wb_collect.wb_orders_backfill_days"
    run_id, started_at = new_run_context(task_name)
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    now_day = datetime.now(UTC).date()
    start_day = now_day - timedelta(days=safe_days)
    total_rows = 0
    latest_seen_ts: datetime | None = None

    ch_client = get_ch_client()
    redis_client = get_redis_client()
    try:
        with lock_scope(redis_client=redis_client, source="wb_orders", account_id=account_id, ttl_seconds=1800):
            for day_cursor, _ in date_chunks(start_day, now_day, chunk_days=1):
                records = wb.orders_for_day(day_cursor)
                rows = parse_orders(records, run_id=run_id, account_id=account_id)
                total_rows += _insert_rows(ch_client, "raw_wb_orders", RAW_WB_ORDERS_COLUMNS, rows)
                if rows:
                    day_latest = max(row["last_change_ts"] for row in rows)
                    day_latest_utc = day_latest.replace(tzinfo=UTC)
                    if latest_seen_ts is None or day_latest_utc > latest_seen_ts:
                        latest_seen_ts = day_latest_utc

            if latest_seen_ts is not None:
                set_watermark(ch_client, "wb_orders", account_id, latest_seen_ts)
            log_task_run(
                ch_client,
                task_name,
                run_id,
                started_at,
                "success",
                total_rows,
                f"wb orders backfill by day ({safe_days} days)",
            )
            return {"status": "success", "rows": total_rows, "days": safe_days}
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}
    except Exception as exc:
        log_task_run(ch_client, task_name, run_id, started_at, "failed", total_rows, str(exc))
        raise
    finally:
        ch_client.close()


@shared_task(name="tasks.wb_collect.wb_funnel_backfill_days")
def wb_funnel_backfill_days(days: int = 14, account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    safe_days = max(1, min(days, 365))
    task_name = "tasks.wb_collect.wb_funnel_backfill_days"
    run_id, started_at = new_run_context(task_name)
    wb = _wb_client()
    if wb is None:
        return {"status": "skipped", "reason": "missing WB tokens"}

    now_day = datetime.now(UTC).date()
    start_day = now_day - timedelta(days=safe_days)

    total_rows = 0
    ch_client = get_ch_client()
    redis_client = get_redis_client()
    try:
        with lock_scope(redis_client=redis_client, source="wb_funnel", account_id=account_id, ttl_seconds=1200):
            for chunk_from, chunk_to in date_chunks(start_day, now_day, chunk_days=3):
                records = wb.funnel_daily(from_day=chunk_from, to_day=chunk_to)
                rows = parse_funnel(records, run_id=run_id, account_id=account_id)
                total_rows += _insert_rows(ch_client, "raw_wb_funnel_daily", RAW_WB_FUNNEL_COLUMNS, rows)

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
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}
    except Exception as exc:
        log_task_run(ch_client, task_name, run_id, started_at, "failed", total_rows, str(exc))
        raise
    finally:
        ch_client.close()
