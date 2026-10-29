"""Ozon collection tasks."""

from __future__ import annotations

import logging
import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
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
    parse_finance_balance,
    parse_postings,
    parse_stocks,
)
from common.finance import FINANCE_CATEGORIES
from common.pnl_tax import realization_totals
from collectors.ozon.sku_ad_reports import fetch_report, cache_key, parse_report, report_is_fresh
from common.ozon_buyouts import parse_buyouts
from common.funnel_economics import campaign_metadata_rows

LOGGER = logging.getLogger(__name__)

OZON_ACCOUNT_ID = os.getenv("OZON_ACCOUNT_ID", "default")
# Ozon dates accruals and ad statistics by the Moscow calendar day
OZON_TZ = ZoneInfo("Europe/Moscow")
# accruals of recent days are still being posted, so every run re-reads them
FINANCE_LOOKBACK_DAYS = 3
ADS_LOOKBACK_DAYS = 3
POSTINGS_LOOKBACK_DAYS = 90


@shared_task(name='tasks.ozon_collect.ozon_buyouts_week')
def ozon_buyouts_week(days: int = 7, account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    """Daily buyout snapshots. Explicitly bounded to the latest week."""
    days=max(1,min(days,7))
    ozon=_ozon_client()
    if ozon is None:return {'status':'skipped','reason':'missing Ozon credentials'}
    ch=get_ch_client();run_id,started=new_run_context()
    task='tasks.ozon_collect.ozon_buyouts_week';day=_ozon_today()-timedelta(days=days-1)
    count=0
    with lock_scope(redis_client=get_redis_client(),source='ozon_buyouts',account_id=account_id,
                    ttl_seconds=900,auto_renew=True):
        try:
            while day<=_ozon_today():
                payload=ozon.finance_buyouts(day,day)
                parsed=parse_buyouts(payload)
                raw=json.dumps(payload,ensure_ascii=False,sort_keys=True)
                ch.insert('raw_ozon_buyouts_daily',[[account_id,day,len(parsed),raw,
                    hashlib.sha256(raw.encode()).hexdigest(),datetime.now(UTC)]],
                    column_names=['account_id','day','row_count','payload','sha256','fetched_at'])
                count+=len(parsed);day+=timedelta(days=1)
            log_task_run(ch,task,run_id,started,'success',count,'CIS buyouts refreshed',meta={'days':days})
            return {'status':'success','rows':count,'days':days}
        except Exception as exc:
            log_task_run(ch,task,run_id,started,'failed',count,str(exc));raise
        finally:ozon.close()


@shared_task(name="tasks.ozon_collect.ozon_ads_sku_backfill_days")
def ozon_ads_sku_backfill_days(days: int = 3, account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    """Read-only asynchronous reports; no campaign/bid/budget writes."""
    perf = _ozon_performance_client()
    if perf is None:
        return {"status":"skipped","reason":"missing Performance credentials"}
    ch = get_ch_client()
    run_id, started = new_run_context()
    task_name = 'tasks.ozon_collect.ozon_ads_sku_backfill_days'
    stop = _ozon_today()-timedelta(days=1)
    cursor = _ozon_today()-timedelta(days=max(1,min(days,730)))
    inserted = 0
    reports = 0
    with lock_scope(redis_client=get_redis_client(),source='ozon_sku_ads',account_id=account_id,
                    ttl_seconds=1800,auto_renew=True):
        try:
            while cursor <= stop:
                # Stable daily buckets avoid generating overlapping rolling reports.
                end = cursor
                campaigns = [str(r[0]) for r in ch.query(
                    "SELECT DISTINCT campaign_id FROM ("
                    " SELECT JSONExtractString(payload,'unit_number') AS campaign_id FROM raw_ozon_finance_ops FINAL"
                    " WHERE account_id={aid:String} AND operation_ts>=toDateTime({start:Date},'Europe/Moscow')"
                    " AND operation_ts<toDateTime(addDays({stop:Date},1),'Europe/Moscow')"
                    " AND JSONExtractInt(payload,'non_item_fee','type_id') IN (41,75)"
                    " UNION ALL SELECT campaign_id FROM raw_ozon_ads_daily FINAL"
                    " WHERE account_id={aid:String} AND day BETWEEN {start:Date} AND {stop:Date}"
                    " UNION ALL SELECT campaign_id FROM raw_ozon_ads_sku_daily FINAL"
                    " WHERE account_id={aid:String} AND day BETWEEN {start:Date} AND {stop:Date}"
                    ") WHERE campaign_id != '' ORDER BY campaign_id",
                    parameters={'aid':account_id,'start':cursor,'stop':end}).result_rows]
                for offset in range(0,len(campaigns),10):
                    batch=campaigns[offset:offset+10]
                    key=cache_key(account_id,batch,cursor,end)
                    saved=ch.query('SELECT report_uuid,payload,updated_at FROM raw_ozon_sku_report_jobs FINAL WHERE cache_key={key:String}',parameters={'key':key}).result_rows
                    if saved and saved[0][1] and not report_is_fresh(saved[0][2], _ozon_today()):
                        # Recent days can be corrected; reuse completed jobs only today.
                        saved = []
                    def save_job(uuid,payload=''):
                        ch.insert('raw_ozon_sku_report_jobs',[[key,account_id,cursor,end,json.dumps(batch),uuid,payload,datetime.now(UTC)]],
                                  column_names=['cache_key','account_id','date_from','date_to','campaigns','report_uuid','payload','updated_at'])
                    if saved and saved[0][1]:
                        uuid=saved[0][0]
                        records=parse_report(json.loads(saved[0][1]),batch,cursor,end)
                    else:
                        records,uuid,raw=fetch_report(perf,batch,cursor,end,
                            job_uuid=saved[0][0] if saved else None,on_created=save_job)
                        save_job(uuid,json.dumps(raw,ensure_ascii=False))
                    # A correction can remove a SKU entirely from the report. Store
                    # a zero revision too, so old cost does not remain in economics.
                    previous = ch.query(
                        'SELECT day,campaign_id,sku FROM raw_ozon_ads_sku_daily FINAL'
                        ' WHERE account_id={aid:String} AND day BETWEEN {start:Date} AND {stop:Date}'
                        ' AND campaign_id IN {campaigns:Array(String)}',
                        parameters={'aid':account_id,'start':cursor,'stop':end,'campaigns':batch},
                    ).result_rows
                    for day,campaign,sku in previous:
                        records.setdefault((day,str(campaign),str(sku)),0)
                    rows = [[account_id,day,campaign,sku,amount,uuid,datetime.now(UTC)]
                            for (day,campaign,sku),amount in records.items()]
                    if rows:
                        ch.insert('raw_ozon_ads_sku_daily',rows,column_names=[
                            'account_id','day','campaign_id','sku','cost','report_uuid','fetched_at'])
                    inserted += len(rows)
                    reports += 1
                    LOGGER.info('sku_ads_report_saved period=%s..%s rows=%s reports=%s',cursor,end,len(rows),reports)
                cursor=end+timedelta(days=1)
            log_task_run(ch,task_name,run_id,started,'success',inserted,'Performance SKU reports collected',
                         meta={'days':days,'reports':reports})
            return {'status':'success','rows':inserted,'reports':reports}
        except Exception as exc:
            log_task_run(ch,task_name,run_id,started,'failed',inserted,str(exc),meta={'reports':reports})
            raise
        finally:
            perf.close()


@shared_task(name="tasks.ozon_collect.ozon_realization_backfill_days")
def ozon_realization_backfill_days(days: int = 62, account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    """Keep original reports and validated totals for completed calendar months."""
    if os.getenv("PNL_REALIZATION_TAX_ENABLED", "false").lower() != "true":
        return {"status": "skipped", "reason": "realization tax disabled"}
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}
    ch = get_ch_client()
    run_id, started = new_run_context()
    task_name = "tasks.ozon_collect.ozon_realization_backfill_days"
    fetched, unavailable = [], []
    today = _ozon_today()
    month = (today - timedelta(days=max(1, min(days, 730)))).replace(day=1)
    with lock_scope(redis_client=get_redis_client(), source="ozon_realization", account_id=account_id,
                    ttl_seconds=600, auto_renew=True):
        try:
            while month < today.replace(day=1):
                try:
                    payload = ozon.finance_realization(month.year, month.month)
                    sales, returns = realization_totals(payload, month)
                except (ValueError, httpx.HTTPStatusError) as exc:
                    # Missing/rejected reports remain visibly unavailable in P&L; no zero estimate.
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {400, 404}:
                        raise
                    unavailable.append(month.isoformat())
                    LOGGER.warning("realization_unavailable month=%s error=%s", month, type(exc).__name__)
                else:
                    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    ch.insert("raw_ozon_realization_monthly", [[
                        account_id, month, sales, returns, len(payload['result']['rows']),
                        "/v2/finance/realization", hashlib.sha256(raw.encode()).hexdigest(), raw,
                        datetime.now(UTC),
                    ]], column_names=["account_id", "month", "sales_amount", "returns_amount", "row_count",
                                      "source", "sha256", "payload", "fetched_at"])
                    fetched.append(month.isoformat())
                month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
            log_task_run(ch, task_name, run_id, started, "success", len(fetched),
                         "monthly realization reports collected", meta={"months": fetched, "unavailable": unavailable})
            return {"status": "success", "months": fetched, "unavailable": unavailable}
        except Exception as exc:
            log_task_run(ch, task_name, run_id, started, "failed", len(fetched), str(exc))
            raise
        finally:
            ozon.close()

RAW_OZON_FINANCE_BALANCE_COLUMNS = [
    "run_id",
    "account_id",
    "day",
    *FINANCE_CATEGORIES,
    "net_accrued",
    "payouts",
    "opening_balance",
    "closing_balance",
    "services",
    "payload",
]

RAW_MARKETPLACE_BALANCE_COLUMNS = [
    "run_id",
    "marketplace",
    "account_id",
    "snapshot_ts",
    "balance",
    "for_withdraw",
    "payload",
]

# the seller's balance history starts with the first sale; the method answers zeros before
FINANCE_BALANCE_EARLIEST_DAY = date(2022, 1, 1)
FINANCE_BALANCE_LOOKBACK_DAYS = 3

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


def _capability_detail(exc: Exception) -> str:
    """Status, path and a short body of the failed call, so a skip stays diagnosable."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return str(exc)[:300]
    request = exc.request
    body = " ".join(exc.response.text.split())[:300]
    return f"{exc.response.status_code} {request.method} {request.url.path}: {body}"


def _log_capability_skip(
    ch_client: Any,
    task_name: str,
    run_id: str,
    started_at: datetime,
    source: str,
    exc: Exception,
) -> None:
    detail = _capability_detail(exc)
    LOGGER.warning("ozon %s capability unavailable: %s", source, detail)
    log_task_run(
        ch_client,
        task_name,
        run_id,
        started_at,
        "skipped",
        0,
        f"ozon {source} capability unavailable: {detail}",
        meta={"capability": source, "reason": "unavailable_or_forbidden", "error": detail},
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
            now_ts = datetime.now(UTC)
            watermark = from_ts if from_ts is not None else min(
                get_watermark(ch_client, "ozon_postings", account_id),
                now_ts - timedelta(days=POSTINGS_LOOKBACK_DAYS),
            )
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
                _log_capability_skip(ch_client, task_name, run_id, started_at, "postings", exc)
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
    safe_days = max(1, min(days, 730))
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
                _log_capability_skip(ch_client, task_name, run_id, started_at, "finance", exc)
                return {"status": "skipped", "reason": "capability_unavailable"}
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise


def _collect_finance_balance(account_id: str, from_day: date) -> dict[str, Any]:
    """Daily balance rows from ``from_day`` to today and a snapshot of the current balance."""
    task_name = "tasks.ozon_collect.ozon_finance_balance"
    run_id, started_at = new_run_context()
    ozon = _ozon_client()
    if ozon is None:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    redis_client = get_redis_client()
    with lock_scope(
        redis_client=redis_client,
        source="ozon_finance_balance",
        account_id=account_id,
        ttl_seconds=1200,
        auto_renew=True,
    ):
        ch_client = get_ch_client()
        try:
            today = _ozon_today()
            start_day = min(max(from_day, FINANCE_BALANCE_EARLIEST_DAY), today)
            rows: list[dict[str, Any]] = []
            day = start_day
            while day <= today:
                rows.append(
                    parse_finance_balance(
                        ozon.finance_balance(day, day),
                        day=day,
                        run_id=run_id,
                        account_id=account_id,
                    )
                )
                day += timedelta(days=1)
            inserted = insert_rows(
                ch_client, "raw_ozon_finance_balance", RAW_OZON_FINANCE_BALANCE_COLUMNS, rows
            )
            # today's closing balance is the balance the seller cabinet shows right now
            current = rows[-1]
            insert_rows(
                ch_client,
                "raw_marketplace_balance",
                RAW_MARKETPLACE_BALANCE_COLUMNS,
                [
                    {
                        "run_id": run_id,
                        "marketplace": "ozon",
                        "account_id": account_id,
                        "snapshot_ts": datetime.now(UTC).replace(microsecond=0),
                        "balance": current["closing_balance"],
                        "for_withdraw": None,
                        "payload": current["payload"],
                    }
                ],
            )
            set_watermark(
                ch_client,
                "ozon_finance_balance",
                account_id,
                datetime.combine(today, datetime.min.time(), tzinfo=OZON_TZ).astimezone(UTC),
            )
            log_task_run(
                ch_client,
                task_name,
                run_id,
                started_at,
                "success",
                inserted,
                "ozon balance collected",
                meta={"from_day": start_day.isoformat(), "to_day": today.isoformat()},
            )
            return {
                "status": "success",
                "rows": inserted,
                "balance": current["closing_balance"],
                "from_day": start_day.isoformat(),
                "to_day": today.isoformat(),
            }
        except Exception as exc:
            if is_capability_error(exc):
                _log_capability_skip(ch_client, task_name, run_id, started_at, "balance", exc)
                return {"status": "skipped", "reason": "capability_unavailable"}
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise


@shared_task(name="tasks.ozon_collect.ozon_finance_balance")
def ozon_finance_balance(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    try:
        # Catch up after downtime instead of permanently missing balance days.
        today = _ozon_today()
        watermark_day = get_watermark(
            get_ch_client(), "ozon_finance_balance", account_id
        ).astimezone(OZON_TZ).date()
        return _collect_finance_balance(
            account_id=account_id,
            from_day=min(today, watermark_day) - timedelta(days=FINANCE_BALANCE_LOOKBACK_DAYS),
        )
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_finance_balance_backfill_days")
def ozon_finance_balance_backfill_days(
    days: int = 30, account_id: str = OZON_ACCOUNT_ID
) -> dict[str, Any]:
    safe_days = max(1, min(days, 730))
    try:
        result = _collect_finance_balance(
            account_id=account_id, from_day=_ozon_today() - timedelta(days=safe_days)
        )
        result["days"] = safe_days
        return result
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_finance_incremental")
def ozon_finance_incremental(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    try:
        return _collect_finance(account_id=account_id)
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.ozon_collect.ozon_finance_backfill_days")
def ozon_finance_backfill_days(days: int = 30, account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    safe_days = max(1, min(days, 730))
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
                try:
                    metadata = campaign_metadata_rows(account_id, performance.campaigns())
                    if metadata:
                        ch_client.insert('raw_ozon_campaign_metadata', metadata, column_names=[
                            'account_id','campaign_id','effective_from','payload','fetched_at'])
                except Exception:
                    LOGGER.warning('Campaign metadata refresh failed; collecting daily spend independently', exc_info=True)
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
                    _log_capability_skip(ch_client, task_name, run_id, started_at, "ads", exc)
                    return {"status": "skipped", "reason": "capability_unavailable"}
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
            finally:
                performance.close()
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}
