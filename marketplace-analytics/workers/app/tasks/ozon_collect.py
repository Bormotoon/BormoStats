"""Ozon collection tasks."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

from celery import shared_task

from app.utils.locking import LockNotAcquired, lock_scope
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context
from app.utils.watermarks import get_watermark, set_watermark
from collectors.ozon.client import OzonApiClient
from collectors.ozon.parsers import parse_ads_daily, parse_finance_ops, parse_postings, parse_stocks

OZON_ACCOUNT_ID = os.getenv("OZON_ACCOUNT_ID", "default")

RAW_OZON_POSTINGS_COLUMNS = [
    "run_id",
    "account_id",
    "posting_number",
    "status",
    "created_at",
    "in_process_at",
    "shipped_at",
    "delivered_at",
    "canceled_at",
    "ozon_warehouse_id",
    "payload",
]

RAW_OZON_POSTING_ITEMS_COLUMNS = [
    "run_id",
    "account_id",
    "posting_number",
    "ozon_product_id",
    "offer_id",
    "name",
    "quantity",
    "price",
    "payout",
    "payload",
]

RAW_OZON_STOCKS_COLUMNS = [
    "run_id",
    "account_id",
    "snapshot_ts",
    "ozon_product_id",
    "offer_id",
    "warehouse_id",
    "present",
    "reserved",
    "payload",
]

RAW_OZON_ADS_COLUMNS = [
    "run_id",
    "account_id",
    "day",
    "campaign_id",
    "impressions",
    "clicks",
    "cost",
    "orders",
    "revenue",
    "payload",
]

RAW_OZON_FINANCE_COLUMNS = [
    "run_id",
    "account_id",
    "operation_id",
    "operation_ts",
    "type",
    "amount",
    "currency",
    "payload",
]


def _ozon_client() -> OzonApiClient | None:
    client_id = os.getenv("OZON_CLIENT_ID", "")
    api_key = os.getenv("OZON_API_KEY", "")
    perf_api_key = os.getenv("OZON_PERF_API_KEY", "")
    if not client_id or not api_key:
        return None
    return OzonApiClient(client_id=client_id, api_key=api_key, perf_api_key=perf_api_key)


def _postings_schemas() -> tuple[str, ...]:
    raw = os.getenv("OZON_POSTINGS_SCHEMAS", "fbs,fbo")
    items = [item.strip().lower() for item in raw.split(",") if item.strip()]
    valid = [item for item in items if item in {"fbs", "fbo"}]
    if not valid:
        return ("fbs",)
    return tuple(dict.fromkeys(valid))


def _insert_rows(client: Any, table: str, columns: list[str], rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    data = [[row.get(col) for col in columns] for row in rows]
    client.insert(table=table, data=data, column_names=columns)
    return len(rows)


def _collect_postings(account_id: str, from_ts: datetime | None = None) -> dict[str, Any]:
    task_name = "tasks.ozon_collect.ozon_postings_incremental"
    run_id, started_at = new_run_context(task_name)
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    redis_client = get_redis_client()
    with lock_scope(redis_client=redis_client, source="ozon_postings", account_id=account_id, ttl_seconds=1200):
        ch_client = get_ch_client()
        try:
            watermark = from_ts or get_watermark(ch_client, "ozon_postings", account_id)
            now_ts = datetime.now(UTC)
            records = ozon.postings_since(
                from_ts=watermark,
                to_ts=now_ts,
                schemas=_postings_schemas(),
            )
            posting_rows, item_rows = parse_postings(records, run_id=run_id, account_id=account_id)

            inserted = 0
            inserted += _insert_rows(ch_client, "raw_ozon_postings", RAW_OZON_POSTINGS_COLUMNS, posting_rows)
            inserted += _insert_rows(
                ch_client,
                "raw_ozon_posting_items",
                RAW_OZON_POSTING_ITEMS_COLUMNS,
                item_rows,
            )

            set_watermark(ch_client, "ozon_postings", account_id, now_ts)
            log_task_run(ch_client, task_name, run_id, started_at, "success", inserted, "ozon postings collected")
            return {"status": "success", "rows": inserted, "watermark": now_ts.isoformat()}
        except Exception as exc:
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise
        finally:
            ch_client.close()


def _collect_finance(account_id: str, from_ts: datetime | None = None) -> dict[str, Any]:
    task_name = "tasks.ozon_collect.ozon_finance_incremental"
    run_id, started_at = new_run_context(task_name)
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    redis_client = get_redis_client()
    with lock_scope(redis_client=redis_client, source="ozon_finance", account_id=account_id, ttl_seconds=1200):
        ch_client = get_ch_client()
        try:
            watermark = from_ts or get_watermark(ch_client, "ozon_finance", account_id)
            now_ts = datetime.now(UTC)
            records = ozon.finance_operations(from_ts=watermark, to_ts=now_ts, limit=1000)
            rows = parse_finance_ops(records, run_id=run_id, account_id=account_id)
            inserted = _insert_rows(ch_client, "raw_ozon_finance_ops", RAW_OZON_FINANCE_COLUMNS, rows)

            latest_ts = max((row["operation_ts"] for row in rows), default=now_ts.replace(tzinfo=None))
            set_watermark(ch_client, "ozon_finance", account_id, latest_ts.replace(tzinfo=UTC))
            log_task_run(ch_client, task_name, run_id, started_at, "success", inserted, "ozon finance ops collected")
            return {"status": "success", "rows": inserted, "watermark": str(latest_ts)}
        except Exception as exc:
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise
        finally:
            ch_client.close()


@shared_task(name="tasks.ozon_collect.ozon_postings_incremental")
def ozon_postings_incremental(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    try:
        return _collect_postings(account_id=account_id)
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_postings_backfill_days")
def ozon_postings_backfill_days(days: int = 14, account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    safe_days = max(1, min(days, 90))
    try:
        result = _collect_postings(account_id=account_id, from_ts=datetime.now(UTC) - timedelta(days=safe_days))
        result["days"] = safe_days
        return result
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_finance_incremental")
def ozon_finance_incremental(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    try:
        return _collect_finance(account_id=account_id)
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_finance_backfill_days")
def ozon_finance_backfill_days(days: int = 30, account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    safe_days = max(1, min(days, 365))
    try:
        result = _collect_finance(account_id=account_id, from_ts=datetime.now(UTC) - timedelta(days=safe_days))
        result["days"] = safe_days
        return result
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_stocks_snapshot")
def ozon_stocks_snapshot(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    task_name = "tasks.ozon_collect.ozon_stocks_snapshot"
    run_id, started_at = new_run_context(task_name)
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    snapshot_ts = datetime.now(UTC)
    redis_client = get_redis_client()
    try:
        with lock_scope(redis_client=redis_client, source="ozon_stocks", account_id=account_id, ttl_seconds=900):
            ch_client = get_ch_client()
            try:
                records = ozon.stocks()
                rows = parse_stocks(records, run_id=run_id, account_id=account_id, snapshot_ts=snapshot_ts)
                inserted = _insert_rows(ch_client, "raw_ozon_stocks", RAW_OZON_STOCKS_COLUMNS, rows)
                log_task_run(ch_client, task_name, run_id, started_at, "success", inserted, "ozon stocks snapshot")
                return {"status": "success", "rows": inserted}
            except Exception as exc:
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
            finally:
                ch_client.close()
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_ads_daily")
def ozon_ads_daily(target_day: str | None = None, account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    task_name = "tasks.ozon_collect.ozon_ads_daily"
    run_id, started_at = new_run_context(task_name)
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    day_value = date.fromisoformat(target_day) if target_day else (datetime.now(UTC).date() - timedelta(days=1))

    redis_client = get_redis_client()
    try:
        with lock_scope(redis_client=redis_client, source="ozon_ads", account_id=account_id, ttl_seconds=900):
            ch_client = get_ch_client()
            try:
                records = ozon.ads_daily(day_value)
                rows = parse_ads_daily(records, run_id=run_id, account_id=account_id)
                inserted = _insert_rows(ch_client, "raw_ozon_ads_daily", RAW_OZON_ADS_COLUMNS, rows)
                log_task_run(ch_client, task_name, run_id, started_at, "success", inserted, "ozon ads daily")
                return {"status": "success", "rows": inserted, "day": day_value.isoformat()}
            except Exception as exc:
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
            finally:
                ch_client.close()
    except LockNotAcquired:
        return {"status": "skipped", "reason": "lock_not_acquired"}
