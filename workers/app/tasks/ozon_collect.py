"""Ozon collection tasks."""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.utils.celery_helpers import shared_task
from app.utils.collection import collect_snapshot, insert_rows
from app.utils.locking import LockNotAcquiredError, lock_scope
from app.utils.metrics import observe_empty_payload
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context
from app.utils.watermarks import get_watermark, set_watermark

from collectors.ozon import endpoints
from collectors.ozon.client import OzonApiClient, OzonPerformanceClient
from collectors.ozon.errors import is_capability_error
from collectors.ozon.parsers import (
    parse_ads_daily,
    parse_finance_accruals,
    parse_postings,
    parse_stocks,
)

LOGGER = logging.getLogger(__name__)

OZON_ACCOUNT_ID = os.getenv("OZON_ACCOUNT_ID", "default")
# Ozon dates accruals and ad statistics by the Moscow calendar day
OZON_TZ = ZoneInfo("Europe/Moscow")
# accruals of recent days are still being posted, so every run re-reads them
FINANCE_LOOKBACK_DAYS = 3
ADS_LOOKBACK_DAYS = 3

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
    "source",
    "payload",
]


def _ozon_client() -> OzonApiClient | None:
    client_id = os.getenv("OZON_CLIENT_ID", "")
    api_key = os.getenv("OZON_API_KEY", "")
    if not client_id or not api_key:
        return None
    return OzonApiClient(client_id=client_id, api_key=api_key)


def _ozon_performance_client() -> OzonPerformanceClient | None:
    client_id = os.getenv("OZON_PERF_CLIENT_ID", "").strip()
    client_secret = os.getenv("OZON_PERF_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return OzonPerformanceClient(client_id=client_id, client_secret=client_secret)


def _ozon_today() -> date:
    return datetime.now(OZON_TZ).date()


def _postings_schemas() -> tuple[str, ...]:
    raw = os.getenv("OZON_POSTINGS_SCHEMAS", "fbs,fbo")
    items = [item.strip().lower() for item in raw.split(",") if item.strip()]
    valid = [item for item in items if item in {"fbs", "fbo"}]
    if not valid:
        return ("fbs",)
    return tuple(dict.fromkeys(valid))


def _log_capability_skip(
    ch_client: Any,
    task_name: str,
    run_id: str,
    started_at: datetime,
    source: str,
) -> None:
    log_task_run(
        ch_client,
        task_name,
        run_id,
        started_at,
        "skipped",
        0,
        f"ozon {source} capability unavailable",
        meta={"capability": source, "reason": "unavailable_or_forbidden"},
    )


# -- Postings tasks --


def _collect_postings(account_id: str, from_ts: datetime | None = None) -> dict[str, Any]:
    task_name = "tasks.ozon_collect.ozon_postings_incremental"
    run_id, started_at = new_run_context()
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    redis_client = get_redis_client()
    with lock_scope(
        redis_client=redis_client,
        source="ozon_postings",
        account_id=account_id,
        ttl_seconds=1200,
        auto_renew=True,
    ):
        ch_client = get_ch_client()
        try:
            watermark = from_ts or get_watermark(ch_client, "ozon_postings", account_id)
            now_ts = datetime.now(UTC)
            records = ozon.postings_since(
                from_ts=watermark,
                to_ts=now_ts,
                schemas=_postings_schemas(),
            )
            if not records:
                observe_empty_payload("ozon_postings")
            posting_rows, item_rows = parse_postings(records, run_id=run_id, account_id=account_id)

            inserted = insert_rows(
                ch_client,
                "raw_ozon_postings",
                RAW_OZON_POSTINGS_COLUMNS,
                posting_rows,
            )
            inserted += insert_rows(
                ch_client,
                "raw_ozon_posting_items",
                RAW_OZON_POSTING_ITEMS_COLUMNS,
                item_rows,
            )

            set_watermark(ch_client, "ozon_postings", account_id, now_ts)
            log_task_run(
                ch_client,
                task_name,
                run_id,
                started_at,
                "success",
                inserted,
                "ozon postings collected",
            )
            return {"status": "success", "rows": inserted, "watermark": now_ts.isoformat()}
        except Exception as exc:
            if is_capability_error(exc):
                _log_capability_skip(ch_client, task_name, run_id, started_at, "postings")
                return {"status": "skipped", "reason": "capability_unavailable"}
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise


@shared_task(name="tasks.ozon_collect.ozon_postings_incremental")
def ozon_postings_incremental(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    try:
        return _collect_postings(account_id=account_id)
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_postings_backfill_days")
def ozon_postings_backfill_days(
    days: int = 14, account_id: str = OZON_ACCOUNT_ID
) -> dict[str, Any]:
    safe_days = max(1, min(days, 90))
    try:
        result = _collect_postings(
            account_id=account_id, from_ts=datetime.now(UTC) - timedelta(days=safe_days)
        )
        result["days"] = safe_days
        return result
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


# -- Finance tasks --


def _finance_start_day(watermark: datetime, today: date) -> date:
    start = watermark.astimezone(OZON_TZ).date() - timedelta(days=FINANCE_LOOKBACK_DAYS)
    return min(max(start, endpoints.FINANCE_ACCRUAL_EARLIEST_DAY), today)


def _accrual_type_names(ozon: OzonApiClient) -> dict[int, str]:
    """Type names only label rows, so a failing dictionary must not block collection."""
    try:
        return ozon.finance_accrual_types()
    except Exception:
        LOGGER.warning("ozon accrual types unavailable; rows are labelled by type id")
        return {}


def _collect_finance(account_id: str, from_day: date | None = None) -> dict[str, Any]:
    task_name = "tasks.ozon_collect.ozon_finance_incremental"
    run_id, started_at = new_run_context()
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    redis_client = get_redis_client()
    with lock_scope(
        redis_client=redis_client,
        source="ozon_finance",
        account_id=account_id,
        ttl_seconds=1200,
        auto_renew=True,
    ):
        ch_client = get_ch_client()
        try:
            today = _ozon_today()
            if from_day is None:
                start_day = _finance_start_day(
                    get_watermark(ch_client, "ozon_finance", account_id), today
                )
            else:
                start_day = min(max(from_day, endpoints.FINANCE_ACCRUAL_EARLIEST_DAY), today)
            type_names = _accrual_type_names(ozon)

            inserted = 0
            day = start_day
            while day <= today:
                records = ozon.finance_accruals_for_day(day)
                rows = parse_finance_accruals(
                    records, run_id=run_id, account_id=account_id, type_names=type_names
                )
                inserted += insert_rows(
                    ch_client,
                    "raw_ozon_finance_ops",
                    RAW_OZON_FINANCE_COLUMNS,
                    rows,
                )
                day += timedelta(days=1)

            # written once: watermarks share a second-precision updated_at, so several
            # writes per run would be ambiguous; re-reading after a failure is idempotent
            today_start = datetime.combine(today, datetime.min.time(), tzinfo=OZON_TZ)
            set_watermark(ch_client, "ozon_finance", account_id, today_start.astimezone(UTC))

            if inserted == 0:
                observe_empty_payload("ozon_finance")
            log_task_run(
                ch_client,
                task_name,
                run_id,
                started_at,
                "success",
                inserted,
                "ozon finance accruals collected",
                meta={"from_day": start_day.isoformat(), "to_day": today.isoformat()},
            )
            return {
                "status": "success",
                "rows": inserted,
                "from_day": start_day.isoformat(),
                "to_day": today.isoformat(),
            }
        except Exception as exc:
            if is_capability_error(exc):
                _log_capability_skip(ch_client, task_name, run_id, started_at, "finance")
                return {"status": "skipped", "reason": "capability_unavailable"}
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise


@shared_task(name="tasks.ozon_collect.ozon_finance_incremental")
def ozon_finance_incremental(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    try:
        return _collect_finance(account_id=account_id)
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_finance_backfill_days")
def ozon_finance_backfill_days(days: int = 30, account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    safe_days = max(1, min(days, 365))
    try:
        result = _collect_finance(
            account_id=account_id, from_day=_ozon_today() - timedelta(days=safe_days)
        )
        result["days"] = safe_days
        return result
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


# -- Stocks tasks --


@shared_task(name="tasks.ozon_collect.ozon_stocks_snapshot")
def ozon_stocks_snapshot(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    def fetch() -> list[dict[str, Any]]:
        items = ozon.stocks()
        skus = [
            int(stock["sku"])
            for item in items
            for stock in item.get("stocks") or []
            if isinstance(stock, dict) and str(stock.get("sku") or "").isdigit()
        ]
        try:
            fbo_rows = ozon.fbo_stocks(skus)
        except Exception as exc:
            # FBO stocks need the analytics role; FBS stocks are still worth storing
            if not is_capability_error(exc):
                raise
            LOGGER.warning("ozon FBO stocks unavailable: %s", exc)
            fbo_rows = []
        return items + fbo_rows

    return collect_snapshot(
        task_name="tasks.ozon_collect.ozon_stocks_snapshot",
        source="ozon_stocks",
        account_id=account_id,
        fetch_fn=fetch,
        parse_fn=parse_stocks,
        columns=RAW_OZON_STOCKS_COLUMNS,
        table="raw_ozon_stocks",
    )


# -- Ads tasks --


@shared_task(name="tasks.ozon_collect.ozon_ads_daily")
def ozon_ads_daily(
    target_day: str | None = None, account_id: str = OZON_ACCOUNT_ID
) -> dict[str, Any]:
    """Collect Performance API daily campaign stats (``target_day`` or the last days)."""
    task_name = "tasks.ozon_collect.ozon_ads_daily"
    run_id, started_at = new_run_context()
    performance = _ozon_performance_client()
    if performance is None:
        ch_client = get_ch_client()
        log_task_run(
            ch_client,
            task_name,
            run_id,
            started_at,
            "skipped",
            0,
            "ozon ads disabled: missing OZON_PERF_CLIENT_ID / OZON_PERF_CLIENT_SECRET",
            meta={"capability": "ads", "reason": "missing_performance_credentials"},
        )
        return {"status": "skipped", "reason": "missing_performance_credentials"}

    if target_day:
        from_day = to_day = date.fromisoformat(target_day)
    else:
        # statistics of the last days are still adjusted by Ozon, so they are re-read
        to_day = _ozon_today() - timedelta(days=1)
        from_day = to_day - timedelta(days=ADS_LOOKBACK_DAYS - 1)

    redis_client = get_redis_client()
    try:
        with lock_scope(
            redis_client=redis_client,
            source="ozon_ads",
            account_id=account_id,
            ttl_seconds=900,
            auto_renew=True,
        ):
            ch_client = get_ch_client()
            try:
                records = performance.daily_stats(from_day, to_day)
                if not records:
                    observe_empty_payload("ozon_ads")
                rows = parse_ads_daily(records, run_id=run_id, account_id=account_id)
                inserted = insert_rows(ch_client, "raw_ozon_ads_daily", RAW_OZON_ADS_COLUMNS, rows)
                log_task_run(
                    ch_client,
                    task_name,
                    run_id,
                    started_at,
                    "success",
                    inserted,
                    "ozon ads daily",
                )
                return {
                    "status": "success",
                    "rows": inserted,
                    "from_day": from_day.isoformat(),
                    "to_day": to_day.isoformat(),
                }
            except Exception as exc:
                if is_capability_error(exc):
                    _log_capability_skip(ch_client, task_name, run_id, started_at, "ads")
                    return {"status": "skipped", "reason": "capability_unavailable"}
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
            finally:
                performance.close()
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}
