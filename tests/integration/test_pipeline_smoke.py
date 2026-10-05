from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

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
                "saleID": "S1001",
                "lastChangeDate": self.recent_ts.isoformat(),
                "date": self.recent_ts.isoformat(),
                "nmId": 111,
                "chrtId": 222,
                "barcode": "wb-sku-111",
                "quantity": 2,
                "totalPrice": 250.0,
                "priceWithDisc": 100.0,
                "forPay": 80.0,
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
                "warehouseId": -999999,
                "warehouseName": "Склад WB",
                "regionName": "Склад WB",
                "quantity": 7,
                "inWayToClient": 1,
                "inWayFromClient": 0,
            }
        ]

    def account_balance(self) -> dict[str, object]:
        return {"currency": "RUB", "current": 12044.0, "for_withdraw": 0}

    def sales_report_lines(self, date_from: date, date_to: date) -> list[dict[str, object]]:
        day = self.recent_ts.astimezone(ozon_collect.OZON_TZ).date()
        if not date_from <= day <= date_to:
            return []

        def line(rrd_id: int, doc: str, oper: str, **money: float) -> dict[str, object]:
            return {
                "rrdId": rrd_id,
                "reportId": 77,
                "reportType": 1,
                "rrDate": day.isoformat(),
                "nmId": 111,
                "docTypeName": doc,
                "sellerOperName": oper,
                "quantity": 1 if doc else 0,
                **{key: str(value) for key, value in money.items()},
            }

        return [
            line(1, "Продажа", "Продажа", retailPriceWithDisc=100, forPay=80, acquiringFee=3),
            line(2, "", "Логистика", deliveryService=30),
            line(3, "", "Хранение", paidStorage=5),
            line(4, "Возврат", "Возврат", retailPriceWithDisc=100, forPay=80, acquiringFee=3),
        ]

    def close(self) -> None:
        pass

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


def _ozon_realization(accrual_id: int, day: date, *, sign: int) -> dict[str, object]:
    """A POSTING accrual: the sale of one unit at 200 (commission 50), or its reversal."""

    def money(value: float) -> dict[str, str]:
        return {"amount": str(value), "currency": "RUB"}

    return {
        "accrual_id": accrual_id,
        "date": day.isoformat(),
        "accrued_category": "POSTING",
        "unit_number": "ozon-posting-1",
        "posting": {
            "delivery_schema": "Fbo",
            "products": [
                {
                    "sku": 100500,
                    "quantity": 1,
                    "delivery": None,
                    "commission": {
                        "seller_price": money(sign * 200),
                        "sale_amount": money(sign * 200),
                        "commission": money(sign * -50),
                    },
                }
            ],
        },
        "total_amount": money(sign * 150),
    }


class FakeOzonApi:
    def __init__(self, recent_ts: datetime) -> None:
        self.recent_ts = recent_ts
        self.accrual_day = recent_ts.astimezone(ozon_collect.OZON_TZ).date()

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
                "delivery_method": {"id": 5, "warehouse_id": 2},
                "products": [
                    {
                        "sku": 100500,
                        "offer_id": "offer-1",
                        "name": "Ozon product",
                        "quantity": 1,
                        "price": {"amount": "200.0000", "currency": "RUB"},
                    }
                ],
                "financial_data": {
                    "products": [{"product_id": 100500, "price": 200.0, "payout": 150.0}]
                },
            }
        ]

    def finance_balance(self, date_from: date, date_to: date) -> dict[str, object]:
        def money(value: float) -> dict[str, object]:
            return {"value": value, "currency_code": "RUB"}

        if date_from != self.accrual_day:
            # a day without movements carries the balance over
            carried = money(955.0 if date_from > self.accrual_day else 1000.0)
            return {
                "total": {
                    "opening_balance": carried,
                    "closing_balance": carried,
                    "accrued": money(0),
                    "payments": [],
                },
                "cashflows": {},
            }
        return {
            "total": {
                "opening_balance": money(1000.0),
                "closing_balance": money(955.0),
                "accrued": money(55.0),
                "payments": [money(-100.0)],
            },
            "cashflows": {
                "sales": {"amount": money(200.0), "fee": money(-100.0)},
                "returns": {"amount": money(0.0), "fee": money(0.0)},
                "services": [
                    {"name": "logistics", "amount": money(-30.0)},
                    {"name": "product_placement_in_ozon_warehouses", "amount": money(-10.0)},
                    {"name": "some_new_service", "amount": money(-5.0)},
                ],
            },
        }

    def finance_accrual_types(self) -> dict[int, str]:
        return {10: "ServiceFee"}

    def finance_accruals_for_day(self, day: date) -> list[dict[str, object]]:
        if day != self.accrual_day:
            return []
        return [
            {
                "accrual_id": 9001,
                "date": day.isoformat(),
                "accrued_category": "NON_ITEM",
                "unit_number": "ad-contract-1",
                "non_item_fee": {"type_id": 10, "accrued": {"amount": "-12.5", "currency": "RUB"}},
                "total_amount": {"amount": "-12.5", "currency": "RUB"},
            },
            _ozon_realization(9002, day, sign=1),
            _ozon_realization(9003, day, sign=-1),
        ]

    def stocks(self) -> list[dict[str, object]]:
        return [
            {
                "product_id": 7001,
                "offer_id": "offer-1",
                "stocks": [
                    {
                        "sku": 100500,
                        "type": "fbs",
                        "warehouse_ids": [2],
                        "present": 9,
                        "reserved": 2,
                    }
                ],
            }
        ]

    def fbo_stocks(self, skus: list[int]) -> list[dict[str, object]]:
        assert skus == [100500]
        return []


class FakeOzonPerformance:
    def __init__(self, recent_ts: datetime) -> None:
        self.recent_ts = recent_ts

    def daily_stats(self, from_day: date, to_day: date) -> list[dict[str, object]]:
        if not from_day <= self.recent_ts.date() <= to_day:
            return []
        return [
            {
                "id": "camp-1",
                "title": "Campaign",
                "date": self.recent_ts.date().isoformat(),
                "views": "1000",
                "clicks": "50",
                "moneySpent": "25,00",
                "orders": "3",
                "ordersMoney": "300,00",
            }
        ]

    def close(self) -> None:
        pass


def _ingest_sample_marketplace_data(monkeypatch: pytest.MonkeyPatch) -> date:
    recent_ts = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
    monkeypatch.setattr(wb_collect, "_wb_client", lambda: FakeWbApi(recent_ts))
    monkeypatch.setattr(ozon_collect, "_ozon_client", lambda: FakeOzonApi(recent_ts))
    monkeypatch.setattr(
        ozon_collect, "_ozon_performance_client", lambda: FakeOzonPerformance(recent_ts)
    )

    assert wb_collect.wb_sales_incremental()["status"] == "success"
    assert wb_collect.wb_orders_incremental()["status"] == "success"
    assert wb_collect.wb_stocks_snapshot()["status"] == "success"
    assert wb_collect.wb_funnel_roll()["status"] == "success"
    assert ozon_collect.ozon_postings_incremental()["status"] == "success"
    assert ozon_collect.ozon_finance_incremental()["status"] == "success"
    assert ozon_collect.ozon_finance_balance()["status"] == "success"
    assert wb_collect.wb_finance_report()["status"] == "success"
    assert wb_collect.wb_balance_snapshot()["status"] == "success"
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
        from warehouse import apply_migrations as migration_module

        expected = {m.version for m in migration_module.discover_migrations()}
        before_rows = client.query("SELECT count() FROM sys_schema_migrations").result_rows[0][0]
        before = migration_module.load_applied_versions(client, integration_runtime.ch_db)

        applied_again = migration_module.apply_migrations()
        after_rows = client.query("SELECT count() FROM sys_schema_migrations").result_rows[0][0]

        assert tables == {"sys_watermarks", "stg_sales", "mrt_sales_daily"}
        assert before == expected
        assert applied_again == []
        assert after_rows == before_rows
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
            SELECT marketplace, product_id, qty, price_gross, payout, is_return
            FROM stg_sales
            ORDER BY marketplace, product_id, qty
            """).result_rows
        stg_order_count = client.query("SELECT count() FROM stg_orders").result_rows[0][0]
        stg_stock_count = client.query("SELECT count() FROM stg_stocks").result_rows[0][0]
        finance_rows = client.query(
            "SELECT operation_id, type, amount, currency FROM stg_finance_ops ORDER BY operation_id"
        ).result_rows
        product_count = client.query("SELECT count() FROM dim_product").result_rows[0][0]

        # Ozon sales are the realization accruals: the sale and the return's reversal
        assert stg_sales_rows == [
            ("ozon", "100500", -1, 200.0, -150.0, 1),
            ("ozon", "100500", 1, 200.0, 150.0, 0),
            ("wb", "111", 2, 100.0, 80.0, 0),
        ]
        assert stg_order_count == 2
        assert stg_stock_count == 2
        assert [row[0] for row in finance_rows] == ["9001", "9002", "9003"]
        assert finance_rows[0] == ("9001", "ServiceFee", -12.5, "RUB")
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
            SELECT marketplace, product_id, qty, revenue, payout, returns_qty
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

        # sold 1, returned 1: revenue counts the sale, payout is net of the reversal
        assert sales_rows == [
            ("ozon", "100500", 1, 200.0, 0.0, 1),
            ("wb", "111", 2, 200.0, 80.0, 0),
        ]
        # WB stock is per card (nm_id), the grain of sales
        assert stock_rows == [("ozon", "100500", 7), ("wb", "111", 7)]
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
            "title": None,  # no catalogue in the smoke stack
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
            "returns_30d": 1,
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
        # sys_watermarks is a ReplacingMergeTree on (source, account_id): a background
        # merge would collapse the history the monotonicity check inspects
        client.command("SYSTEM STOP MERGES sys_watermarks")
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

    try:
        with pytest.raises(RuntimeError) as exc_info:
            maintenance.run_data_quality_checks()
    finally:
        client = integration_runtime.ch_client()
        try:
            client.command("SYSTEM START MERGES sys_watermarks")
        finally:
            client.close()

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


def test_finance_block_reconciles(
    integration_runtime,
    monkeypatch: pytest.MonkeyPatch,
    api_client: TestClient,
) -> None:
    recent_day = _ingest_sample_marketplace_data(monkeypatch)
    assert transforms.transform_backfill_days(14)["status"] == "success"
    assert marts.build_marts_backfill_days(14)["status"] == "success"

    client = integration_runtime.ch_client()
    try:
        rows = {
            (row[0], row[1]): row[2:]
            for row in client.query("""
                SELECT marketplace, day, sales, returns, commission, acquiring, logistics,
                       storage, other, net_accrued, payouts, closing_balance, for_withdraw
                FROM mrt_finance_daily FINAL
                WHERE net_accrued != 0 OR closing_balance IS NOT NULL
                """).result_rows
        }
        pnl = client.query("""
            SELECT marketplace, sum(revenue_rub), sum(net_accrued_rub), sum(gross_profit_rub)
            FROM mrt_pnl_monthly FINAL
            GROUP BY marketplace ORDER BY marketplace
            """).result_rows
    finally:
        client.close()

    ozon = next(v for k, v in rows.items() if k[0] == "ozon" and v[7] != 0)
    # sales 200, commission -100, logistics -30, storage -10, unknown service -5 -> other
    assert ozon[:9] == (200.0, 0.0, -100.0, 0.0, -30.0, -10.0, -5.0, 55.0, -100.0)
    assert ozon[9] == 955.0

    wb = next(v for k, v in rows.items() if k[0] == "wb" and v[7] != 0)
    # sale 80 for pay, return -80, logistics -30, storage -5: WB's "Итого к оплате" = -35
    assert wb[0] == 100.0 and wb[1] == -100.0
    assert wb[4] == -30.0 and wb[5] == -5.0
    assert wb[7] == pytest.approx(-35.0)
    assert wb[2] + wb[3] == 0.0  # commission and acquiring cancel out with the return

    wb_balance = [v for k, v in rows.items() if k[0] == "wb" and v[9] is not None]
    assert wb_balance and wb_balance[-1][9] == 12044.0 and wb_balance[-1][10] == 0.0

    assert pnl == [("ozon", 200.0, 55.0, 55.0), ("wb", 100.0, -35.0, -35.0)]

    balance = api_client.get("/api/v1/finance/balance")
    assert balance.status_code == 200
    assert {(i["marketplace"], i["balance"]) for i in balance.json()["items"]} == {
        ("ozon", 955.0),
        ("wb", 12044.0),
    }
    daily = api_client.get(
        "/api/v1/finance/daily",
        params={"date_from": recent_day.isoformat(), "date_to": date.today().isoformat()},
    )
    assert daily.status_code == 200
    assert sum(i["net_accrued"] for i in daily.json()["items"]) == pytest.approx(55.0 - 35.0)


def test_every_collected_table_is_archived_and_readable_at_a_point_in_time(
    integration_runtime,
    monkeypatch: pytest.MonkeyPatch,
    api_client: TestClient,
) -> None:
    _ingest_sample_marketplace_data(monkeypatch)

    client = integration_runtime.ch_client()
    try:
        archived = {
            row[0] for row in client.query("SELECT DISTINCT repo FROM hist_refs").result_rows
        }
        collected = {
            row[0]
            for row in client.query(
                "SELECT name FROM system.tables WHERE database = currentDatabase()"
                " AND name LIKE 'raw\\\\_%' AND name NOT LIKE 'raw\\\\_competitor%'"
                " AND name != 'raw_serp_positions' AND total_rows > 0"
            ).result_rows
        }
    finally:
        client.close()

    # every non-empty raw table of the seller's own data has a history repo
    assert collected <= archived, collected - archived

    now = api_client.get("/api/v1/history/state", params={"repo": "raw_marketplace_balance"})
    assert now.status_code == 200
    assert {(i["marketplace"], i["document"]["balance"]) for i in now.json()["items"]} == {
        ("ozon", 955.0),
        ("wb", 12044.0),
    }
    before = api_client.get(
        "/api/v1/history/state",
        params={"repo": "raw_marketplace_balance", "at": "2020-01-01T00:00:00Z"},
    )
    assert before.status_code == 200 and before.json()["items"] == []
