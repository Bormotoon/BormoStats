from __future__ import annotations

# ruff: noqa: E402, I001

import asyncio
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import clickhouse_connect
import httpx
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
WORKERS_DIR = ROOT_DIR / "workers"

for path in (BACKEND_DIR, WORKERS_DIR, ROOT_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

os_environ = {
    "ADMIN_API_KEY": "perf-admin-key",
    "CH_USER": "analytics_app",
    "CH_PASSWORD": "perf-clickhouse-password",
    "CH_HOST": "localhost",
    "CH_PORT": "8123",
    "CH_DB": "mp_analytics",
    "REDIS_URL": "redis://localhost:6379/0",
}
for key, value in os_environ.items():
    os.environ.setdefault(key, value)

from app.core.config import get_settings
from app.core.deps import _get_cached_ch_client, get_app_settings, get_ch_client
from app.main import app
from app.tasks import marts, transforms
from app.utils.runtime import (
    get_ch_client as get_worker_ch_client,
    get_redis_client,
)

from tests.integration.conftest import (
    CLICKHOUSE_IMAGE,
    REDIS_IMAGE,
    TRUNCATE_TABLES,
    IntegrationEnv,
    _provision_clickhouse_app_user,
    _published_port,
    _remove_container,
    _run_command,
    _runtime_env_scope,
    _wait_for_clickhouse,
    _wait_for_redis,
)
from tests.integration.test_pipeline_smoke import _ingest_sample_marketplace_data
from warehouse import apply_migrations

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
def _perf_runtime() -> IntegrationEnv:
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
            apply_migrations.apply_migrations()
            get_settings.cache_clear()
            _get_cached_ch_client.cache_clear()
            get_worker_ch_client.cache_clear()
            get_redis_client.cache_clear()
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
        total = 0
        for table_name in RAW_TABLES:
            total += int(client.query(f"SELECT count() FROM {table_name}").result_rows[0][0])
        return total
    finally:
        client.close()


async def _run_api_latency_smoke(env: IntegrationEnv, target_day: str) -> dict[str, float | int]:
    ch_client = clickhouse_connect.get_client(
        host=env.ch_host,
        port=env.ch_port,
        username=env.ch_user,
        password=env.ch_password,
        database=env.ch_db,
        autogenerate_session_id=False,
    )
    settings = SimpleNamespace(
        redis_url=env.redis_url,
        admin_api_key=env.admin_api_key,
    )
    app.dependency_overrides[get_ch_client] = lambda: ch_client
    app.dependency_overrides[get_app_settings] = lambda: settings

    latencies_ms: list[float] = []
    total_requests = 50
    concurrency = 10
    semaphore = asyncio.Semaphore(concurrency)

    try:
        transport = httpx.ASGITransport(app=app)
        limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            limits=limits,
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
