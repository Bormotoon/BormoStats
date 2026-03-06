from __future__ import annotations

# ruff: noqa: E402, I001

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import clickhouse_connect
import httpx
import pytest
from redis import Redis

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
WORKERS_DIR = ROOT_DIR / "workers"

for path in (BACKEND_DIR, WORKERS_DIR, ROOT_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

for key, value in {
    "ADMIN_API_KEY": "perf-admin-key",
    "CH_USER": "analytics_app",
    "CH_PASSWORD": "perf-clickhouse-password",
    "CH_HOST": "localhost",
    "CH_PORT": "8123",
    "CH_DB": "mp_analytics",
    "REDIS_URL": "redis://localhost:6379/0",
}.items():
    os.environ.setdefault(key, value)

from app.core.config import get_settings
from app.core.deps import _get_cached_ch_client, get_app_settings, get_ch_client
from app.main import app
from app.tasks import marts, transforms
from app.utils.runtime import get_ch_client as get_worker_ch_client, get_redis_client
from warehouse import apply_migrations

CLICKHOUSE_IMAGE = (
    "clickhouse/clickhouse-server@sha256:"
    "51beb66e790213a53ddacacf133d3067106f5aa0c446c5b40b9b0c3ae0cd39fc"
)
REDIS_IMAGE = "redis@sha256:ee64a64eaab618d88051c3ade8f6352d11531fcf79d9a4818b9b183d8c1d18ba"
TRUNCATE_TABLES = (
    "sys_watermarks",
    "sys_task_runs",
    "dim_product",
    "raw_wb_sales",
    "raw_wb_orders",
    "raw_wb_stocks",
    "raw_wb_funnel_daily",
    "raw_ozon_postings",
    "raw_ozon_posting_items",
    "raw_ozon_stocks",
    "raw_ozon_ads_daily",
    "raw_ozon_finance_ops",
    "stg_sales",
    "stg_orders",
    "stg_stocks",
    "stg_funnel_daily",
    "stg_ads_daily",
    "stg_finance_ops",
    "mrt_sales_daily",
    "mrt_stock_daily",
    "mrt_funnel_daily",
    "mrt_ads_daily",
)
RAW_TABLES = (
    "raw_wb_sales",
    "raw_wb_orders",
    "raw_wb_stocks",
    "raw_wb_funnel_daily",
    "raw_ozon_postings",
    "raw_ozon_posting_items",
    "raw_ozon_stocks",
    "raw_ozon_ads_daily",
    "raw_ozon_finance_ops",
)


@dataclass(frozen=True)
class IntegrationEnv:
    ch_host: str
    ch_port: int
    ch_user: str
    ch_password: str
    ch_db: str
    redis_url: str
    admin_api_key: str

    def ch_client(self) -> clickhouse_connect.driver.Client:
        return clickhouse_connect.get_client(
            host=self.ch_host,
            port=self.ch_port,
            username=self.ch_user,
            password=self.ch_password,
            database=self.ch_db,
            autogenerate_session_id=False,
        )

    def redis_client(self) -> Redis:
        return Redis.from_url(self.redis_url)


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


def _run_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=True)


def _remove_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True, text=True)


def _published_port(container_name: str, container_port: str) -> int:
    output = _run_command("docker", "port", container_name, container_port).stdout.strip()
    return int(output.rsplit(":", maxsplit=1)[1])


def _wait_for_clickhouse(host: str, port: int) -> None:
    deadline = time.monotonic() + 90
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/ping", timeout=5.0) as response:
                if response.read().decode("utf-8").strip().startswith("Ok"):
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"ClickHouse did not become ready: {last_error}")


def _wait_for_redis(redis_url: str) -> None:
    deadline = time.monotonic() + 30
    client = Redis.from_url(redis_url)
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if client.ping():
                return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Redis did not become ready: {last_error}")


def _provision_clickhouse_app_user(
    env: IntegrationEnv,
    admin_user: str,
    admin_password: str,
) -> None:
    admin_client = clickhouse_connect.get_client(
        host=env.ch_host,
        port=env.ch_port,
        username=admin_user,
        password=admin_password,
        database="default",
        autogenerate_session_id=False,
    )
    try:
        admin_client.command("CREATE DATABASE IF NOT EXISTS `mp_analytics`")
        admin_client.command(
            "CREATE USER IF NOT EXISTS `analytics_app` "
            "IDENTIFIED WITH plaintext_password BY %(password)s",
            parameters={"password": env.ch_password},
        )
        admin_client.command("GRANT ALL ON `mp_analytics`.* TO `analytics_app`")
    finally:
        admin_client.close()


def _runtime_env_values(env: IntegrationEnv) -> dict[str, str]:
    return {
        "ADMIN_API_KEY": env.admin_api_key,
        "CH_HOST": env.ch_host,
        "CH_PORT": str(env.ch_port),
        "CH_USER": env.ch_user,
        "CH_PASSWORD": env.ch_password,
        "CH_DB": env.ch_db,
        "REDIS_URL": env.redis_url,
        "WB_TOKEN_STATISTICS": "integration-wb-statistics-token",
        "WB_TOKEN_ANALYTICS": "integration-wb-analytics-token",
        "OZON_CLIENT_ID": "integration-ozon-client-id",
        "OZON_API_KEY": "integration-ozon-api-key",
        "OZON_PERF_API_KEY": "integration-ozon-perf-key",
        "OZON_POSTINGS_SCHEMAS": "fbs,fbo",
    }


@contextmanager
def _runtime_env_scope(env: IntegrationEnv) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in _runtime_env_values(env)}
    os.environ.update(_runtime_env_values(env))
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _ingest_sample_marketplace_data(monkeypatch: pytest.MonkeyPatch) -> date:
    from app.tasks import ozon_collect, wb_collect

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


def _truncate_runtime_state(env: IntegrationEnv) -> None:
    client = env.ch_client()
    redis_client = env.redis_client()
    try:
        redis_client.flushdb()
        for table_name in TRUNCATE_TABLES:
            client.command(f"TRUNCATE TABLE {table_name}")
    finally:
        redis_client.close()
        client.close()


@contextmanager
def _perf_runtime() -> Iterator[IntegrationEnv]:
    suffix = uuid4().hex[:8]
    clickhouse_name = f"marketplace-perf-clickhouse-{suffix}"
    redis_name = f"marketplace-perf-redis-{suffix}"
    admin_user = "bootstrap_admin"
    admin_password = "bootstrap-secret-password"
    base_env = IntegrationEnv(
        ch_host="127.0.0.1",
        ch_port=0,
        ch_user="analytics_app",
        ch_password="perf-clickhouse-password",
        ch_db="mp_analytics",
        redis_url="",
        admin_api_key="perf-admin-key",
    )

    try:
        _run_command(
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            clickhouse_name,
            "-e",
            f"CLICKHOUSE_USER={admin_user}",
            "-e",
            f"CLICKHOUSE_PASSWORD={admin_password}",
            "-e",
            "CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1",
            "-p",
            "127.0.0.1::8123",
            CLICKHOUSE_IMAGE,
        )
        _run_command(
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            redis_name,
            "-p",
            "127.0.0.1::6379",
            REDIS_IMAGE,
            "redis-server",
            "--appendonly",
            "no",
            "--save",
            "",
        )

        prepared_env = IntegrationEnv(
            ch_host="127.0.0.1",
            ch_port=_published_port(clickhouse_name, "8123/tcp"),
            ch_user=base_env.ch_user,
            ch_password=base_env.ch_password,
            ch_db=base_env.ch_db,
            redis_url=f"redis://127.0.0.1:{_published_port(redis_name, '6379/tcp')}/15",
            admin_api_key=base_env.admin_api_key,
        )
        _wait_for_clickhouse(prepared_env.ch_host, prepared_env.ch_port)
        _wait_for_redis(prepared_env.redis_url)
        _provision_clickhouse_app_user(prepared_env, admin_user, admin_password)

        with _runtime_env_scope(prepared_env):
            get_settings.cache_clear()
            _get_cached_ch_client.cache_clear()
            get_worker_ch_client.cache_clear()
            get_redis_client.cache_clear()
            apply_migrations.apply_migrations()
            _truncate_runtime_state(prepared_env)
            yield prepared_env
    finally:
        get_settings.cache_clear()
        _get_cached_ch_client.cache_clear()
        get_worker_ch_client.cache_clear()
        get_redis_client.cache_clear()
        _remove_container(clickhouse_name)
        _remove_container(redis_name)


def _raw_row_count(env: IntegrationEnv) -> int:
    client = env.ch_client()
    try:
        return sum(
            int(client.query(f"SELECT count() FROM {table_name}").result_rows[0][0])
            for table_name in RAW_TABLES
        )
    finally:
        client.close()


async def _run_api_latency_smoke(env: IntegrationEnv, target_day: str) -> dict[str, float | int]:
    ch_client = env.ch_client()
    settings = SimpleNamespace(redis_url=env.redis_url, admin_api_key=env.admin_api_key)
    app.dependency_overrides[get_ch_client] = lambda: ch_client
    app.dependency_overrides[get_app_settings] = lambda: settings

    latencies_ms: list[float] = []
    total_requests = 50
    concurrency = 10
    semaphore = asyncio.Semaphore(concurrency)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        ) as client:

            async def make_request() -> None:
                async with semaphore:
                    started_at = time.perf_counter()
                    response = await client.get(
                        "/api/v1/sales/daily",
                        params={
                            "marketplace": "wb",
                            "account_id": "default",
                            "date_from": target_day,
                            "date_to": target_day,
                        },
                    )
                    response.raise_for_status()
                    latencies_ms.append((time.perf_counter() - started_at) * 1000.0)

            started_at = time.perf_counter()
            await asyncio.gather(*(make_request() for _ in range(total_requests)))
            total_duration = time.perf_counter() - started_at
    finally:
        app.dependency_overrides.clear()
        ch_client.close()

    ordered = sorted(latencies_ms)
    p95_index = max(int(len(ordered) * 0.95) - 1, 0)
    return {
        "requests": total_requests,
        "concurrency": concurrency,
        "p50_ms": round(ordered[len(ordered) // 2], 2),
        "p95_ms": round(ordered[p95_index], 2),
        "max_ms": round(max(ordered), 2),
        "throughput_rps": round(total_requests / total_duration, 2),
    }


def main() -> int:
    with _perf_runtime() as env:
        with _runtime_env_scope(env):
            monkeypatch = pytest.MonkeyPatch()
            try:
                ingest_started_at = time.perf_counter()
                target_day = _ingest_sample_marketplace_data(monkeypatch)
                ingest_duration = time.perf_counter() - ingest_started_at
            finally:
                monkeypatch.undo()

            raw_rows = _raw_row_count(env)

            transform_started_at = time.perf_counter()
            transform_result = transforms.transform_backfill_days(14)
            transform_duration = time.perf_counter() - transform_started_at

            marts_started_at = time.perf_counter()
            marts_result = marts.build_marts_backfill_days(14)
            marts_duration = time.perf_counter() - marts_started_at

            api_metrics = asyncio.run(_run_api_latency_smoke(env, target_day.isoformat()))

    report = {
        "measured_at": "2026-03-06",
        "ingestion": {
            "duration_s": round(ingest_duration, 3),
            "raw_rows": raw_rows,
            "throughput_rows_per_s": (
                round(raw_rows / ingest_duration, 2) if ingest_duration else raw_rows
            ),
        },
        "transforms": {
            "duration_s": round(transform_duration, 3),
            "status": transform_result["status"],
        },
        "marts": {
            "duration_s": round(marts_duration, 3),
            "status": marts_result["status"],
        },
        "api": api_metrics,
        "safe_limits": {
            "worker_concurrency": 4,
            "beat_replicas": 1,
            "transform_rebuilds_in_parallel": 1,
            "marts_rebuilds_in_parallel": 1,
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
