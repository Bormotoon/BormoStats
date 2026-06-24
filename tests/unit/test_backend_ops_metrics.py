from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from prometheus_client import generate_latest

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("CH_USER", "analytics_app")
os.environ.setdefault("CH_PASSWORD", "super-secret-clickhouse-password")
os.environ.setdefault("CH_HOST", "localhost")
os.environ.setdefault("CH_PORT", "8123")
os.environ.setdefault("CH_DB", "mp_analytics")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import app.core.ops_metrics as ops_metrics  # noqa: E402


def _reset_metrics() -> None:
    ops_metrics.service_readiness.clear()
    ops_metrics.redis_memory_used_bytes.set(0)
    ops_metrics.redis_memory_limit_bytes.set(0)
    ops_metrics.redis_memory_utilization_ratio.set(0)
    ops_metrics.clickhouse_disk_free_bytes.clear()
    ops_metrics.clickhouse_disk_total_bytes.clear()
    ops_metrics.clickhouse_disk_free_ratio.clear()


def test_refresh_operational_metrics_populates_gauges(monkeypatch) -> None:
    _reset_metrics()

    class FakeRedis:
        def ping(self) -> bool:
            return True

        def info(self, section: str) -> dict[str, int]:
            assert section == "memory"
            return {"used_memory": 512, "maxmemory": 1024}

    class FakeClickHouseClient:
        def query(self, sql: str):
            if sql == "SELECT 1":
                return SimpleNamespace(result_rows=[(1,)])
            if sql == "SELECT name, free_space, total_space FROM system.disks":
                return SimpleNamespace(result_rows=[("default", 400, 1000)])
            raise AssertionError(sql)

        def close(self) -> None:
            return None

    monkeypatch.setattr(ops_metrics.Redis, "from_url", lambda _: FakeRedis())
    monkeypatch.setattr(ops_metrics, "build_client", lambda settings: FakeClickHouseClient())

    settings = SimpleNamespace(
        redis_url="redis://localhost:6379/0",
        ch_host="localhost",
        ch_port=8123,
        ch_user="analytics_app",
        ch_password="secret",
        ch_db="mp_analytics",
    )
    ops_metrics.refresh_operational_metrics(settings)

    payload = generate_latest().decode("utf-8")
    assert 'service_readiness{service="redis"} 1.0' in payload
    assert 'service_readiness{service="clickhouse"} 1.0' in payload
    assert "redis_memory_utilization_ratio" in payload
    assert 'clickhouse_disk_free_ratio{disk="default"} 0.4' in payload


def test_refresh_operational_metrics_marks_failures(monkeypatch) -> None:
    _reset_metrics()

    class FailingRedis:
        def ping(self) -> bool:
            raise RuntimeError("redis down")

    monkeypatch.setattr(ops_metrics.Redis, "from_url", lambda _: FailingRedis())
    monkeypatch.setattr(
        ops_metrics,
        "build_client",
        lambda settings: (_ for _ in ()).throw(RuntimeError("ch down")),
    )

    settings = SimpleNamespace(
        redis_url="redis://localhost:6379/0",
        ch_host="localhost",
        ch_port=8123,
        ch_user="analytics_app",
        ch_password="secret",
        ch_db="mp_analytics",
    )
    ops_metrics.refresh_operational_metrics(settings)

    payload = generate_latest().decode("utf-8")
    assert 'service_readiness{service="redis"} 0.0' in payload
    assert 'service_readiness{service="clickhouse"} 0.0' in payload
    assert 'clickhouse_disk_free_ratio{disk="default"}' not in payload
