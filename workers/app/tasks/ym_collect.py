"""Yandex Market Partner API collection and backfill tasks."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.utils.celery_helpers import shared_task
from app.utils.collection import insert_rows
from app.utils.locking import LockNotAcquiredError, lock_scope
from app.utils.metrics import observe_empty_payload
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context
from app.utils.watermarks import get_watermark, set_watermark

from collectors.ym.client import YmClient
from collectors.ym.parsers import (
    normalize_report_row,
    parse_offer_mappings,
    parse_orders,
    parse_prices,
    parse_shows_boost,
    parse_shows_sales,
    parse_stocks,
    parse_united_netting,
)

YM_BUSINESS_ID = os.getenv("YM_BUSINESS_ID", "")
YM_CAMPAIGN_ID = os.getenv("YM_CAMPAIGN_ID", "")
YM_ACCOUNT_ID = os.getenv("YM_ACCOUNT_ID") or YM_CAMPAIGN_ID or "default"


def _client() -> YmClient | None:
    key = os.getenv("YM_API_KEY", "")
    return YmClient(key) if key and YM_BUSINESS_ID and YM_CAMPAIGN_ID else None


def _with_product_ids(client: YmClient, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Campaign APIs identify offers, while the catalogue owns marketSku."""
    catalogue = parse_offer_mappings(client.offer_mappings(YM_BUSINESS_ID), "", YM_ACCOUNT_ID)
    by_offer = {row["offer_id"]: row for row in catalogue}

    def enrich(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        offer = str(row.get("offerId") or row.get("shopSku") or row.get("offer_id") or "")
        if offer in by_offer:
            card = by_offer[offer]
            row["marketSku"] = card["market_sku"]
            row["purchasePrice"] = {"value": card["purchase_price"]}
        for key in ("items", "offers"):
            if isinstance(row.get(key), list):
                row[key] = [enrich(item) for item in row[key]]
        return row

    return [enrich(row) for row in records]


def _collect(
    name: str,
    source: str,
    table: str,
    columns: list[str],
    fetch: Any,
    parse: Any,
    *,
    account_id: str = YM_ACCOUNT_ID,
    watermark: bool = False,
) -> dict[str, Any]:
    task_name = f"tasks.ym_collect.{name}"
    run_id, started = new_run_context()
    client = _client()
    if client is None:
        return {"status": "skipped", "reason": "missing Yandex Market credentials"}
    ch = get_ch_client()
    try:
        with lock_scope(
            get_redis_client(),
            source=source,
            account_id=account_id,
            ttl_seconds=1800,
            auto_renew=True,
        ):
            now = datetime.now(UTC)
            records = fetch(client, now)
            if table not in {"raw_ym_campaigns", "dim_ad_campaign", "raw_ym_offer_mappings"}:
                records = _with_product_ids(client, records)
            rows = parse(records, run_id=run_id, account_id=account_id)
            if not rows:
                observe_empty_payload(source)
            inserted = insert_rows(ch, table, columns, rows)
            if watermark:
                set_watermark(ch, source, account_id, now)
        log_task_run(ch, task_name, run_id, started, "success", inserted, f"{source} collected")
        return {"status": "success", "rows": inserted, "run_id": run_id}
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}
    except Exception as exc:
        log_task_run(ch, task_name, run_id, started, "failed", 0, str(exc))
        raise
    finally:
        client.close()


ORDER_COLUMNS = [
    "run_id",
    "account_id",
    "order_id",
    "offer_id",
    "product_id",
    "status",
    "substatus",
    "created_at",
    "updated_at",
    "qty",
    "buyer_price",
    "seller_price",
    "subsidy",
    "payload",
    "ingested_at",
]
STOCK_COLUMNS = [
    "run_id",
    "account_id",
    "offer_id",
    "product_id",
    "warehouse_id",
    "warehouse_name",
    "stock_fit",
    "stock_freeze",
    "snapshot_ts",
    "payload",
]
PRICE_COLUMNS = [
    "run_id",
    "account_id",
    "offer_id",
    "product_id",
    "list_price",
    "seller_price",
    "cofinance_price",
    "purchase_price",
    "buyer_price",
    "commission_pct",
    "logistics_rub",
    "acquiring_rub",
    "snapshot_ts",
    "payload",
]
OFFER_MAPPING_COLUMNS = [
    "run_id",
    "account_id",
    "offer_id",
    "market_sku",
    "name",
    "pictures",
    "purchase_price",
    "payload",
    "ingested_at",
]
FUNNEL_COLUMNS = [
    "run_id",
    "account_id",
    "day",
    "offer_id",
    "product_id",
    "shows",
    "clicks",
    "to_cart",
    "orders",
    "revenue",
    "ingested_at",
]
ADS_COLUMNS = [
    "run_id",
    "account_id",
    "day",
    "campaign_id",
    "offer_id",
    "product_id",
    "impressions",
    "clicks",
    "cost",
    "orders",
    "revenue",
    "ingested_at",
]
FINANCE_COLUMNS = [
    "run_id",
    "account_id",
    "transaction_id",
    "event_date",
    "order_id",
    "offer_id",
    "transaction_type",
    "service_type",
    "amount",
    "payout",
    "payload",
    "ingested_at",
]


def _campaign_business_id(campaign: dict[str, Any]) -> int | None:
    business = campaign.get("business")
    value = business.get("id") if isinstance(business, dict) else campaign.get("businessId")
    try:
        return int(value) if value is not None else None
    except TypeError, ValueError:
        return None


def _dates(from_value: Any, to_value: Any) -> tuple[date, date]:
    end = datetime.now(UTC).date()
    start = (
        from_value.astimezone(UTC).date()
        if isinstance(from_value, datetime)
        else end - timedelta(days=1)
    )
    return start, end


def _orders(days: int, *, recent: bool = False) -> dict[str, Any]:
    safe = max(1, min(days, 365))
    run_id, started = new_run_context()
    client = _client()
    if client is None:
        return {"status": "skipped", "reason": "missing Yandex Market credentials"}
    ch = get_ch_client()
    source = "ym_orders"
    task_name = (
        "tasks.ym_collect.ym_orders_recent"
        if recent
        else "tasks.ym_collect.ym_orders_backfill_days"
    )
    try:
        with lock_scope(
            get_redis_client(),
            source=source,
            account_id=YM_ACCOUNT_ID,
            ttl_seconds=1800,
            auto_renew=True,
        ):
            now = datetime.now(UTC)
            start = (
                get_watermark(ch, source, YM_ACCOUNT_ID).date()
                if recent
                else now.date() - timedelta(days=safe)
            )
            start = max(date(2022, 1, 1), min(start, now.date()))
            records = client.orders(
                YM_BUSINESS_ID, start, now.date(), updated=recent, campaign_id=YM_CAMPAIGN_ID
            )
            records = [
                r for r in records if str(r.get("campaignId", YM_CAMPAIGN_ID)) == YM_CAMPAIGN_ID
            ]
            records = _with_product_ids(client, records)
            rows = parse_orders(records, run_id=run_id, account_id=YM_ACCOUNT_ID)
            inserted = insert_rows(ch, "raw_ym_orders", ORDER_COLUMNS, rows)
            if recent:
                set_watermark(ch, source, YM_ACCOUNT_ID, now)
        log_task_run(ch, task_name, run_id, started, "success", inserted, "ym orders collected")
        return {"status": "success", "rows": inserted, "days": safe, "run_id": run_id}
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}
    except Exception as exc:
        log_task_run(ch, task_name, run_id, started, "failed", 0, str(exc))
        raise
    finally:
        client.close()


@shared_task(name="tasks.ym_collect.ym_orders_recent")
def ym_orders_recent() -> dict[str, Any]:
    return _orders(30, recent=True)


@shared_task(name="tasks.ym_collect.ym_orders_backfill_days")
def ym_orders_backfill_days(days: int = 14) -> dict[str, Any]:
    return _orders(days)


@shared_task(name="tasks.ym_collect.ym_stocks_snapshot")
def ym_stocks_snapshot() -> dict[str, Any]:
    return _collect(
        "ym_stocks_snapshot",
        "ym_stocks",
        "raw_ym_stocks",
        STOCK_COLUMNS,
        lambda c, _: _campaign_rows(c, lambda campaign_id: c.stocks(campaign_id)),
        lambda r, **kw: parse_stocks(r, snapshot_ts=datetime.now(UTC), **kw),
    )


@shared_task(name="tasks.ym_collect.ym_prices_snapshot")
def ym_prices_snapshot() -> dict[str, Any]:
    return _collect(
        "ym_prices_snapshot",
        "ym_prices",
        "raw_ym_prices",
        PRICE_COLUMNS,
        lambda c, _: c.offer_prices(YM_CAMPAIGN_ID),
        lambda r, **kw: parse_prices(r, snapshot_ts=datetime.now(UTC), **kw),
    )


@shared_task(name="tasks.ym_collect.ym_offer_mappings_snapshot")
def ym_offer_mappings_snapshot() -> dict[str, Any]:
    return _collect(
        "ym_offer_mappings_snapshot",
        "ym_catalog",
        "raw_ym_offer_mappings",
        OFFER_MAPPING_COLUMNS,
        lambda c, _: c.offer_mappings(YM_BUSINESS_ID),
        parse_offer_mappings,
    )


def _campaign_rows(client: YmClient, fetch: Any) -> list[dict[str, Any]]:
    if YM_CAMPAIGN_ID:
        campaigns = [YM_CAMPAIGN_ID]
    else:
        campaigns = [
            str(row["id"])
            for row in client.campaigns()
            if row.get("id") is not None
            and _campaign_business_id(row) in {None, int(YM_BUSINESS_ID)}
        ]
    rows: list[dict[str, Any]] = []
    for campaign_id in campaigns:
        rows.extend({**row, "_campaignId": campaign_id} for row in fetch(campaign_id))
    return rows


def _collect_report(
    name: str, report_type: str, days: int, table: str, columns: list[str], parser: Any
) -> dict[str, Any]:
    safe = max(1, min(days, 730))

    def fetch(client: YmClient, now: datetime) -> list[dict[str, Any]]:
        if report_type == "shows-boost":
            shops = [
                r for r in client.campaigns() if _campaign_business_id(r) == int(YM_BUSINESS_ID)
            ]
            if len(shops) != 1 or str(shops[0].get("id")) != YM_CAMPAIGN_ID:
                raise ValueError(
                    "shows-boost report is business-wide; "
                    "cannot attribute it to one of multiple shops"
                )
        start = (now - timedelta(days=safe)).date()
        result: list[dict[str, Any]] = []
        while start <= now.date():
            end = min(start + timedelta(days=29), now.date())
            body: dict[str, Any] = {"dateFrom": start.isoformat(), "dateTo": end.isoformat()}
            if report_type in {"united-netting", "shows-boost"}:
                body["businessId"] = int(YM_BUSINESS_ID)
            else:
                body["campaignId"] = int(YM_CAMPAIGN_ID)
            if report_type == "united-netting":
                body["campaignIds"] = [int(YM_CAMPAIGN_ID)]
            if report_type == "shows-boost":
                body["attributionType"] = "CLICKS"
            if report_type == "shows-sales":
                body["grouping"] = "OFFERS"
            report_rows = [
                normalize_report_row(r) for r in client.generate_and_fetch_report(report_type, body)
            ]
            result.extend(
                {**row, "_campaignId": YM_CAMPAIGN_ID}
                for row in report_rows
                if str(row.get("partnerId") or row.get("campaignId", YM_CAMPAIGN_ID))
                == YM_CAMPAIGN_ID
            )
            start = end + timedelta(days=1)
        return result

    def parse(
        records: list[dict[str, Any]], *, run_id: str, account_id: str
    ) -> list[dict[str, Any]]:
        parsed = parser(records, run_id=run_id, account_id=account_id)
        if table == "raw_ym_finance":
            return [
                {
                    "run_id": run_id,
                    "account_id": account_id,
                    "transaction_id": row.get("transaction_id", ""),
                    "event_date": row["day"],
                    "order_id": row.get("order_id"),
                    "offer_id": row.get("offer_id", ""),
                    "transaction_type": str(row.get("transaction_type") or "accrual"),
                    "service_type": str(row.get("service_type") or ""),
                    "amount": row.get("amount", 0.0),
                    "payout": row.get("payout", 0.0),
                    "payload": row["payload"],
                    "ingested_at": row["ingested_at"],
                }
                for row in parsed
            ]
        if table == "raw_ym_ads":
            return [
                {
                    "run_id": run_id,
                    "account_id": account_id,
                    "day": row["day"],
                    "campaign_id": str(row.get("_campaignId") or YM_CAMPAIGN_ID),
                    "offer_id": row.get("offer_id", ""),
                    "product_id": row.get("product_id", 0),
                    "impressions": row.get("shows", 0),
                    "clicks": row.get("clicks", 0),
                    "cost": row.get("amount", 0.0),
                    "orders": row.get("orders", 0),
                    "revenue": row.get("revenue", 0.0),
                    "ingested_at": row["ingested_at"],
                }
                for row in parsed
            ]
        return [
            {
                "run_id": run_id,
                "account_id": account_id,
                "day": row["day"],
                "offer_id": row.get("offer_id", ""),
                "product_id": row.get("product_id", 0),
                "shows": row.get("shows", 0),
                "clicks": row.get("clicks", 0),
                "to_cart": row.get("to_cart", 0),
                "orders": row.get("orders", 0),
                "revenue": row.get("revenue", 0.0),
                "ingested_at": row["ingested_at"],
            }
            for row in parsed
        ]

    return _collect(name, f"ym_{name.split('_')[1]}", table, columns, fetch, parse, watermark=True)


@shared_task(name="tasks.ym_collect.ym_funnel_recent")
def ym_funnel_recent() -> dict[str, Any]:
    return _collect_report(
        "ym_funnel_recent", "shows-sales", 3, "raw_ym_funnel", FUNNEL_COLUMNS, parse_shows_sales
    )


@shared_task(name="tasks.ym_collect.ym_funnel_backfill_days")
def ym_funnel_backfill_days(days: int = 14) -> dict[str, Any]:
    return _collect_report(
        "ym_funnel_backfill_days",
        "shows-sales",
        days,
        "raw_ym_funnel",
        FUNNEL_COLUMNS,
        parse_shows_sales,
    )


@shared_task(name="tasks.ym_collect.ym_ads_recent")
def ym_ads_recent() -> dict[str, Any]:
    return _collect_report(
        "ym_ads_recent", "shows-boost", 3, "raw_ym_ads", ADS_COLUMNS, parse_shows_boost
    )


@shared_task(name="tasks.ym_collect.ym_finance_recent")
def ym_finance_recent() -> dict[str, Any]:
    return _collect_report(
        "ym_finance_recent",
        "united-netting",
        3,
        "raw_ym_finance",
        FINANCE_COLUMNS,
        parse_united_netting,
    )


@shared_task(name="tasks.ym_collect.ym_finance_backfill_days")
def ym_finance_backfill_days(days: int = 30) -> dict[str, Any]:
    return _collect_report(
        "ym_finance_backfill_days",
        "united-netting",
        days,
        "raw_ym_finance",
        FINANCE_COLUMNS,
        parse_united_netting,
    )


@shared_task(name="tasks.ym_collect.ym_balance_snapshot")
def ym_balance_snapshot() -> dict[str, Any]:
    return {
        "status": "unsupported",
        "reason": "Yandex Market Partner API does not expose a balance endpoint",
    }


@shared_task(name="tasks.ym_collect.ym_campaigns_snapshot")
def ym_campaigns_snapshot() -> dict[str, Any]:
    def parse(
        records: list[dict[str, Any]], *, run_id: str, account_id: str
    ) -> list[dict[str, Any]]:
        import json

        return [
            {
                "run_id": run_id,
                "account_id": account_id,
                "business_id": YM_BUSINESS_ID,
                "campaign_id": str(r["id"]),
                "campaign_name": str(r.get("domain") or ""),
                "business_name": str((r.get("business") or {}).get("name") or ""),
                "campaign_type": str(r.get("placementType") or ""),
                "snapshot_ts": datetime.now(UTC),
                "payload": json.dumps(r),
            }
            for r in records
            if str(r.get("id")) == YM_CAMPAIGN_ID
        ]

    return _collect(
        "ym_campaigns_snapshot",
        "ym_campaigns",
        "raw_ym_campaigns",
        [
            "run_id",
            "account_id",
            "business_id",
            "campaign_id",
            "campaign_name",
            "business_name",
            "campaign_type",
            "snapshot_ts",
            "payload",
        ],
        lambda c, _: c.campaigns(),
        parse,
    )


@shared_task(name="tasks.ym_collect.ym_bids_snapshot")
def ym_bids_snapshot() -> dict[str, Any]:
    def parse(
        records: list[dict[str, Any]], *, run_id: str, account_id: str
    ) -> list[dict[str, Any]]:
        return [
            {
                "campaign_id": str(r["sku"]),
                "marketplace": "ym",
                "account_id": account_id,
                "title": str(r["sku"]),
                "status": "active",
                "current_cpm": float(r["bid"]) / 100,
                "updated_at": datetime.now(UTC),
            }
            for r in records
        ]

    return _collect(
        "ym_bids_snapshot",
        "ym_bids",
        "dim_ad_campaign",
        [
            "campaign_id",
            "marketplace",
            "account_id",
            "title",
            "status",
            "current_cpm",
            "updated_at",
        ],
        lambda c, _: c._paged(f"/v2/businesses/{YM_BUSINESS_ID}/bids/info", {}, 200),
        parse,
    )
