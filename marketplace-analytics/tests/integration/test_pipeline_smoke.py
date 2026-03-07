from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from app.tasks import maintenance, marts, ozon_collect, transforms, wb_collect
from app.utils.locking import LockNotAcquiredError, acquire_lock, release_lock, renew_lock
from app.utils.watermarks import get_watermark, set_watermark
from fastapi.testclient import TestClient


class FakeWbApi:
    def __init__(self, recent_ts: datetime) -> None:
        self.recent_ts = recent_ts

    def sales_since(self, watermark: datetime) -> list[dict[str, object]]:
        if watermark > self.recent_ts:
            return []
        return [
            {
                "srid": "wb-sale-1",
                "lastChangeDate": self.recent_ts.isoformat(),
                "date": self.recent_ts.isoformat(),
                "nmId": 111,
                "chrtId": 222,
                "barcode": "wb-sku-111",
                "quantity": 2,
                "totalPrice": 100.0,
                "ppvzForPay": 80.0,
                "supplierOperName": "Продажа",
            }
        ]

    def orders_since(self, watermark: datetime) -> list[dict[str, object]]:
        if watermark > self.recent_ts:
            return []
        return [
            {
                "odid": "wb-order-1",
                "lastChangeDt": self.recent_ts.isoformat(),
                "date": self.recent_ts.isoformat(),
                "nmId": 111,
                "chrtId": 222,
                "quantity": 2,
                "priceWithDisc": 100.0,
            }
        ]

    def stocks(self) -> list[dict[str, object]]:
        return [
            {
                "nmId": 111,
                "chrtId": 222,
                "sku": "wb-sku-111",
                "warehouseId": 1,
                "quantityFull": 7,
            }
        ]

    def funnel_daily(self, from_day: date, to_day: date) -> list[dict[str, object]]:
        if from_day <= self.recent_ts.date() <= to_day:
            return [
                {
                    "day": self.recent_ts.isoformat(),
                    "nm_id": 111,
                    "views": 100,
                    "addsToCart": 10,
                    "orders": 4,
                    "ordersRevenue": 400.0,
                    "buyouts": 3,
                    "cancels": 1,
                    "addToCartCR": 0.1,
                    "cartToOrderCR": 0.4,
                    "buyoutCR": 0.75,
                    "wishlist": 5,
                    "currency": "RUB",
                }
            ]
        return []


class FakeOzonApi:
    def __init__(self, recent_ts: datetime) -> None:
        self.recent_ts = recent_ts

    def postings_since(
        self,
        *,
        from_ts: datetime,
        to_ts: datetime,
        schemas: tuple[str, ...],
    ) -> list[dict[str, object]]:
        assert schemas == ("fbs", "fbo")
        if from_ts > self.recent_ts or to_ts < self.recent_ts:
            return []
        return [
            {
                "posting_number": "ozon-posting-1",
                "status": "delivered",
                "created_at": self.recent_ts.isoformat().replace("+00:00", "Z"),
                "in_process_at": self.recent_ts.isoformat().replace("+00:00", "Z"),
                "shipment_date": self.recent_ts.isoformat().replace("+00:00", "Z"),
                "delivering_date": self.recent_ts.isoformat().replace("+00:00", "Z"),
                "warehouse_id": 2,
                "products": [
                    {
                        "product_id": 100500,
                        "offer_id": "offer-1",
                        "name": "Ozon product",
                        "quantity": 1,
                        "price": "200.0",
                        "payout": "150.0",
                    }
                ],
            }
        ]

    def finance_operations(
        self,
        *,
        from_ts: datetime,
        to_ts: datetime,
        limit: int,
    ) -> list[dict[str, object]]:
        assert limit == 1000
        if from_ts > self.recent_ts or to_ts < self.recent_ts:
            return []
        return [
            {
                "transaction_id": "fin-1",
                "created_at": self.recent_ts.isoformat().replace("+00:00", "Z"),
                "operation_type": "service_fee",
                "accruals_for_sale": "12.5",
                "currency": "RUB",
            }
        ]

    def stocks(self) -> list[dict[str, object]]:
        return [
            {
                "product_id": 100500,
                "offer_id": "offer-1",
                "stocks": [
                    {
                        "warehouse_id": 2,
                        "present": 9,
                        "reserved": 2,
                    }
                ],
            }
        ]

    def ads_daily(self, target_day: date) -> list[dict[str, object]]:
        if target_day != self.recent_ts.date():
            return []
        return [
            {
                "day": target_day.isoformat(),
                "campaign_id": "camp-1",
                "impressions": 1000,
                "clicks": 50,
                "cost": 25.0,
                "orders": 3,
                "revenue": 300.0,
            }
        ]


def _ingest_sample_marketplace_data(monkeypatch: pytest.MonkeyPatch) -> date:
    recent_ts = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
    monkeypatch.setattr(wb_collect, "_wb_client", lambda: FakeWbApi(recent_ts))
    monkeypatch.setattr(ozon_collect, "_ozon_client", lambda: FakeOzonApi(recent_ts))

    assert wb_collect.wb_sales_incremental()["status"] == "success"
    assert wb_collect.wb_orders_incremental()["status"] == "success"
    assert wb_collect.wb_stocks_snapshot()["status"] == "success"
    assert wb_collect.wb_funnel_roll()["status"] == "success"
    assert ozon_collect.ozon_postings_incremental()["status"] == "success"
    assert ozon_collect.ozon_finance_incremental()["status"] == "success"
    assert ozon_collect.ozon_stocks_snapshot()["status"] == "success"
    assert (
        ozon_collect.ozon_ads_daily(target_day=recent_ts.date().isoformat())["status"] == "success"
    )

    return recent_ts.date()


def test_clickhouse_migrations_are_idempotent(integration_runtime) -> None:
    client = integration_runtime.ch_client()
    try:
        tables = {
            str(row[0])
            for row in client.query(
                """
                SELECT name
                FROM system.tables
                WHERE database = %(database)s
                  AND name IN ('sys_watermarks', 'stg_sales', 'mrt_sales_daily')
                """,
                parameters={"database": integration_runtime.ch_db},
            ).result_rows
        }
        before = client.query("SELECT count() FROM sys_schema_migrations").result_rows[0][0]
        apply_count = len(list((Path("warehouse") / "migrations").glob("*.sql")))

        from warehouse import apply_migrations as migration_module

        migration_module.apply_migrations()
        after = client.query("SELECT count() FROM sys_schema_migrations").result_rows[0][0]

        assert tables == {"sys_watermarks", "stg_sales", "mrt_sales_daily"}
        assert before == apply_count
        assert after == before
    finally:
        client.close()


def test_watermarks_are_monotonic(integration_runtime) -> None:
    client = integration_runtime.ch_client()
    try:
        initial = (datetime.now(UTC) - timedelta(hours=24)).replace(microsecond=0)
        older = initial - timedelta(hours=1)
        newer = initial + timedelta(hours=1)

        assert set_watermark(client, "wb_sales", "default", initial) is True
        assert set_watermark(client, "wb_sales", "default", older) is False
        assert set_watermark(client, "wb_sales", "default", newer) is True
        assert get_watermark(client, "wb_sales", "default") == newer
    finally:
        client.close()


def test_redis_lock_lifecycle_uses_live_redis(integration_runtime) -> None:
    redis_client = integration_runtime.redis_client()
    try:
        lock = acquire_lock(redis_client, "wb_sales", "default", ttl_seconds=5)
        with pytest.raises(LockNotAcquiredError):
            acquire_lock(redis_client, "wb_sales", "default", ttl_seconds=5)

        assert renew_lock(redis_client, lock, ttl_seconds=5) is True
        assert release_lock(redis_client, lock) is True

        second = acquire_lock(redis_client, "wb_sales", "default", ttl_seconds=5)
        assert release_lock(redis_client, second) is True
    finally:
        redis_client.close()


def test_transforms_build_expected_staging_rows(
    integration_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_sample_marketplace_data(monkeypatch)
    result = transforms.transform_backfill_days(14)

    assert result["status"] == "success"

    client = integration_runtime.ch_client()
    try:
        stg_sales_rows = client.query("""
            SELECT marketplace, product_id, qty, price_gross
            FROM stg_sales
            ORDER BY marketplace, product_id
            """).result_rows
        stg_order_count = client.query("SELECT count() FROM stg_orders").result_rows[0][0]
        stg_stock_count = client.query("SELECT count() FROM stg_stocks").result_rows[0][0]
        finance_rows = client.query(
            "SELECT operation_id, type, amount, currency FROM stg_finance_ops"
        ).result_rows
        product_count = client.query("SELECT count() FROM dim_product").result_rows[0][0]

        assert stg_sales_rows == [
            ("ozon", "100500", 1, 200.0),
            ("wb", "111", 2, 100.0),
        ]
        assert stg_order_count == 2
        assert stg_stock_count == 2
        assert finance_rows == [("fin-1", "service_fee", 12.5, "RUB")]
        assert product_count == 2
    finally:
        client.close()


def test_marts_build_expected_aggregates(
    integration_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_sample_marketplace_data(monkeypatch)
    assert transforms.transform_backfill_days(14)["status"] == "success"
    result = marts.build_marts_backfill_days(14)

    assert result["status"] == "success"

    client = integration_runtime.ch_client()
    try:
        sales_rows = client.query("""
            SELECT marketplace, product_id, qty, revenue
            FROM mrt_sales_daily
            ORDER BY marketplace, product_id
            """).result_rows
        stock_rows = client.query("""
            SELECT marketplace, product_id, stock_end
            FROM mrt_stock_daily
            ORDER BY marketplace, product_id
            """).result_rows
        funnel_rows = client.query(
            "SELECT product_id, views, orders, cr_order FROM mrt_funnel_daily"
        ).result_rows
        ads_rows = client.query(
            "SELECT campaign_id, cost, revenue, acos FROM mrt_ads_daily"
        ).result_rows

        assert sales_rows == [("ozon", "100500", 1, 200.0), ("wb", "111", 2, 200.0)]
        assert stock_rows == [("ozon", "100500", 7), ("wb", "222", 7)]
        assert funnel_rows == [("111", 100, 4, 0.04)]
        assert ads_rows == [("camp-1", 25.0, 300.0, pytest.approx(25.0 / 300.0))]
    finally:
        client.close()


def test_pipeline_smoke_bootstrap_ingest_transform_marts_api(
    integration_runtime,
    monkeypatch: pytest.MonkeyPatch,
    api_client: TestClient,
) -> None:
    recent_day = _ingest_sample_marketplace_data(monkeypatch)
    assert transforms.transform_backfill_days(14)["status"] == "success"
    assert marts.build_marts_backfill_days(14)["status"] == "success"

    sales_response = api_client.get(
        "/api/v1/sales/daily",
        params={
            "marketplace": "wb",
            "account_id": "default",
            "date_from": recent_day.isoformat(),
            "date_to": recent_day.isoformat(),
        },
    )
    kpis_response = api_client.get(
        "/api/v1/kpis",
        params={"marketplace": "ozon", "account_id": "default"},
    )
    watermarks_response = api_client.get(
        "/api/v1/admin/watermarks",
        headers={"X-API-Key": integration_runtime.admin_api_key},
    )

    assert sales_response.status_code == 200
    assert sales_response.json()["items"] == [
        {
            "day": recent_day.isoformat(),
            "marketplace": "wb",
            "account_id": "default",
            "product_id": "111",
            "qty": 2,
            "revenue": 200.0,
            "returns_qty": 0,
            "payout": 80.0,
        }
    ]
    assert sales_response.json()["pagination"] == {
        "limit": 1000,
        "offset": 0,
        "returned": 1,
        "next_offset": None,
        "has_more": False,
    }

    assert kpis_response.status_code == 200
    assert kpis_response.json()["items"] == [
        {
            "marketplace": "ozon",
            "account_id": "default",
            "revenue_30d": 200.0,
            "qty_30d": 1,
            "returns_30d": 0,
            "cost_30d": 25.0,
            "acos_30d": pytest.approx(25.0 / 300.0),
        }
    ]
    assert kpis_response.json()["pagination"] == {
        "limit": 1000,
        "offset": 0,
        "returned": 1,
        "next_offset": None,
        "has_more": False,
    }

    assert watermarks_response.status_code == 200
    assert {
        (item["source"], item["account_id"]) for item in watermarks_response.json()["items"]
    } >= {
        ("wb_sales", "default"),
        ("wb_orders", "default"),
        ("ozon_postings", "default"),
        ("ozon_finance", "default"),
    }


def test_data_quality_task_passes_for_clean_pipeline(
    integration_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_sample_marketplace_data(monkeypatch)
    assert transforms.transform_backfill_days(14)["status"] == "success"
    assert marts.build_marts_backfill_days(14)["status"] == "success"

    report = maintenance.run_data_quality_checks()

    assert report["status"] == "success"
    assert report["issue_count"] == 0

    client = integration_runtime.ch_client()
    try:
        latest = client.query("""
            SELECT status, message
            FROM sys_task_runs
            WHERE task_name = 'tasks.maintenance.run_data_quality_checks'
            ORDER BY started_at DESC
            LIMIT 1
            """).result_rows
        assert latest == [("success", "data quality checks passed")]
    finally:
        client.close()


def test_data_quality_task_logs_failures_for_bad_data(
    integration_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_sample_marketplace_data(monkeypatch)
    assert transforms.transform_backfill_days(14)["status"] == "success"
    assert marts.build_marts_backfill_days(14)["status"] == "success"

    client = integration_runtime.ch_client()
    try:
        stale_updated_at = (datetime.now(UTC) - timedelta(hours=6)).replace(tzinfo=None)
        current_day = datetime.now(UTC).date() - timedelta(days=1)
        client.command("TRUNCATE TABLE mrt_ads_daily")
        client.command(
            """
            INSERT INTO mrt_ads_daily
            (
              day,
              marketplace,
              account_id,
              campaign_id,
              impressions,
              clicks,
              cost,
              orders,
              revenue,
              acos,
              romi,
              updated_at
            )
            VALUES (
              %(day)s, 'ozon', 'default', 'stale-camp', 0, 0, 0, 0, 0, 0, 0, %(updated_at)s
            )
            """,
            parameters={"day": current_day, "updated_at": stale_updated_at},
        )
        client.command(
            """
            INSERT INTO sys_watermarks (source, account_id, watermark_ts, updated_at)
            VALUES
              ('wb_sales', 'default', %(newer)s, %(newer)s),
              ('wb_sales', 'default', %(older)s, %(older)s)
            """,
            parameters={
                "newer": (datetime.now(UTC) - timedelta(minutes=10)).replace(tzinfo=None),
                "older": (datetime.now(UTC) - timedelta(minutes=20)).replace(tzinfo=None),
            },
        )
        client.command("""
            INSERT INTO stg_sales
            (
              event_ts,
              marketplace,
              account_id,
              order_id,
              posting_number,
              srid,
              product_id,
              nm_id,
              ozon_product_id,
              offer_id,
              qty,
              price_gross,
              payout,
              is_return,
              last_change_ts,
              meta_json,
              ingested_at
            )
            SELECT
              event_ts,
              marketplace,
              account_id,
              order_id,
              posting_number,
              srid,
              product_id,
              nm_id,
              ozon_product_id,
              offer_id,
              qty,
              price_gross,
              payout,
              is_return,
              last_change_ts,
              meta_json,
              ingested_at
            FROM stg_sales
            LIMIT 1
            """)
        client.command(
            """
            INSERT INTO raw_ozon_postings
            (
              run_id,
              account_id,
              posting_number,
              status,
              created_at,
              in_process_at,
              shipped_at,
              delivered_at,
              canceled_at,
              ozon_warehouse_id,
              payload
            )
            VALUES
            (
              generateUUIDv4(),
              'default',
              'bad-posting',
              'delivered',
              %(created_at)s,
              %(created_at)s,
              %(created_at)s,
              %(delivered_at)s,
              NULL,
              2,
              '{}'
            )
            """,
            parameters={
                "created_at": datetime.now(UTC).replace(tzinfo=None),
                "delivered_at": (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None),
            },
        )
        client.command(
            """
            INSERT INTO mrt_stock_daily
            (day, marketplace, account_id, product_id, warehouse_id, stock_end, updated_at)
            VALUES (%(day)s, 'wb', 'default', 'negative-stock', 1, -5, %(updated_at)s)
            """,
            parameters={
                "day": current_day,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
    finally:
        client.close()

    with pytest.raises(RuntimeError) as exc_info:
        maintenance.run_data_quality_checks()

    assert "stale_marts" in str(exc_info.value)
    assert "watermark_monotonicity" in str(exc_info.value)
    assert "duplicate_grains" in str(exc_info.value)
    assert "impossible_timestamps" in str(exc_info.value)
    assert "invalid_values" in str(exc_info.value)

    client = integration_runtime.ch_client()
    try:
        latest = client.query("""
            SELECT status, meta_json
            FROM sys_task_runs
            WHERE task_name = 'tasks.maintenance.run_data_quality_checks'
            ORDER BY started_at DESC
            LIMIT 1
            """).result_rows[0]
        assert latest[0] == "failed"
        assert "stale_marts" in str(latest[1])
        assert "watermark_monotonicity" in str(latest[1])
        assert "duplicate_grains" in str(latest[1])
        assert "impossible_timestamps" in str(latest[1])
        assert "invalid_values" in str(latest[1])
    finally:
        client.close()
