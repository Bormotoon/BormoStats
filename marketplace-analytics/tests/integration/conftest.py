from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import clickhouse_connect
import pytest
from fastapi.testclient import TestClient
from redis import Redis

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
WORKERS_DIR = ROOT_DIR / "workers"

for path in (BACKEND_DIR, WORKERS_DIR, ROOT_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from warehouse import apply_migrations  # noqa: E402

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
        )

    def redis_client(self) -> Redis:
        return Redis.from_url(self.redis_url)


def _run_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=True)


def _remove_container(name: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", name],
        check=False,
        capture_output=True,
        text=True,
    )


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
        except Exception as exc:  # pragma: no cover - best-effort wait loop
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
        except Exception as exc:  # pragma: no cover - best-effort wait loop
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


@pytest.fixture(scope="session")
def integration_env() -> IntegrationEnv:
    suffix = uuid4().hex[:8]
    clickhouse_name = f"marketplace-it-clickhouse-{suffix}"
    redis_name = f"marketplace-it-redis-{suffix}"
    admin_user = "bootstrap_admin"
    admin_password = "bootstrap-secret-password"
    env = IntegrationEnv(
        ch_host="127.0.0.1",
        ch_port=0,
        ch_user="analytics_app",
        ch_password="integration-clickhouse-password",
        ch_db="mp_analytics",
        redis_url="",
        admin_api_key="integration-admin-key",
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

        clickhouse_port = _published_port(clickhouse_name, "8123/tcp")
        redis_port = _published_port(redis_name, "6379/tcp")
        prepared_env = IntegrationEnv(
            ch_host="127.0.0.1",
            ch_port=clickhouse_port,
            ch_user=env.ch_user,
            ch_password=env.ch_password,
            ch_db=env.ch_db,
            redis_url=f"redis://127.0.0.1:{redis_port}/15",
            admin_api_key=env.admin_api_key,
        )

        _wait_for_clickhouse(prepared_env.ch_host, prepared_env.ch_port)
        _wait_for_redis(prepared_env.redis_url)
        _provision_clickhouse_app_user(prepared_env, admin_user, admin_password)

        with _runtime_env_scope(prepared_env):
            apply_migrations.apply_migrations()
        yield prepared_env
    finally:
        _remove_container(clickhouse_name)
        _remove_container(redis_name)


@pytest.fixture()
def integration_runtime(integration_env: IntegrationEnv) -> IntegrationEnv:
    from app.core.config import get_settings
    from app.core.deps import _get_cached_ch_client
    from app.utils.runtime import get_ch_client, get_redis_client

    with _runtime_env_scope(integration_env):
        get_settings.cache_clear()
        _get_cached_ch_client.cache_clear()
        get_ch_client.cache_clear()
        get_redis_client.cache_clear()

        ch_client = integration_env.ch_client()
        redis_client = integration_env.redis_client()
        try:
            redis_client.flushdb()
            for table_name in TRUNCATE_TABLES:
                ch_client.command(f"TRUNCATE TABLE {table_name}")
        finally:
            redis_client.close()
            ch_client.close()

        yield integration_env

        get_settings.cache_clear()
        _get_cached_ch_client.cache_clear()
        get_ch_client.cache_clear()
        get_redis_client.cache_clear()


@pytest.fixture()
def api_client(integration_runtime: IntegrationEnv) -> TestClient:
    from app.core.deps import get_app_settings, get_ch_client
    from app.main import app

    ch_client = integration_runtime.ch_client()
    settings = SimpleNamespace(
        redis_url=integration_runtime.redis_url,
        admin_api_key=integration_runtime.admin_api_key,
    )
    app.dependency_overrides[get_ch_client] = lambda: ch_client
    app.dependency_overrides[get_app_settings] = lambda: settings

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        ch_client.close()
