"""Operational Prometheus metrics gathered from Redis and ClickHouse."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from app.core.config import Settings
from app.db.ch import build_client
from prometheus_client import Gauge
from redis import Redis

service_readiness = Gauge(
    "service_readiness",
    "Readiness state for internal dependencies",
    ["service"],
)

redis_memory_used_bytes = Gauge(
    "redis_memory_used_bytes",
    "Redis used memory in bytes",
)
redis_memory_limit_bytes = Gauge(
    "redis_memory_limit_bytes",
    "Redis configured maxmemory in bytes",
)
redis_memory_utilization_ratio = Gauge(
    "redis_memory_utilization_ratio",
    "Redis memory usage divided by configured maxmemory",
)

clickhouse_disk_free_bytes = Gauge(
    "clickhouse_disk_free_bytes",
    "ClickHouse free disk space in bytes",
    ["disk"],
)
clickhouse_disk_total_bytes = Gauge(
    "clickhouse_disk_total_bytes",
    "ClickHouse total disk space in bytes",
    ["disk"],
)
clickhouse_disk_free_ratio = Gauge(
    "clickhouse_disk_free_ratio",
    "ClickHouse free disk space divided by total disk space",
    ["disk"],
)


def refresh_operational_metrics(settings: Settings) -> None:
    _refresh_redis_metrics(settings)
    _refresh_clickhouse_metrics(settings)


def _refresh_redis_metrics(settings: Settings) -> None:
    try:
        redis_client = Redis.from_url(settings.redis_url)
        redis_client.ping()
        memory_info = cast(Mapping[str, Any], redis_client.info(section="memory"))
    except Exception:
        service_readiness.labels(service="redis").set(0)
        redis_memory_used_bytes.set(0)
        redis_memory_limit_bytes.set(0)
        redis_memory_utilization_ratio.set(0)
        return

    service_readiness.labels(service="redis").set(1)
    used_memory = _as_float(memory_info.get("used_memory"))
    maxmemory = _as_float(memory_info.get("maxmemory"))
    utilization = (used_memory / maxmemory) if maxmemory > 0 else 0.0

    redis_memory_used_bytes.set(used_memory)
    redis_memory_limit_bytes.set(maxmemory)
    redis_memory_utilization_ratio.set(utilization)


def _refresh_clickhouse_metrics(settings: Settings) -> None:
    try:
        client = build_client(settings)
        try:
            client.query("SELECT 1")
            rows = client.query(
                "SELECT name, free_space, total_space FROM system.disks"
            ).result_rows
        finally:
            client.close()
    except Exception:
        service_readiness.labels(service="clickhouse").set(0)
        clickhouse_disk_free_bytes.clear()
        clickhouse_disk_total_bytes.clear()
        clickhouse_disk_free_ratio.clear()
        return

    service_readiness.labels(service="clickhouse").set(1)
    clickhouse_disk_free_bytes.clear()
    clickhouse_disk_total_bytes.clear()
    clickhouse_disk_free_ratio.clear()
    for disk_name, free_space, total_space in rows:
        disk = str(disk_name)
        free_bytes = _as_float(free_space)
        total_bytes = _as_float(total_space)
        ratio = (free_bytes / total_bytes) if total_bytes > 0 else 0.0

        clickhouse_disk_free_bytes.labels(disk=disk).set(free_bytes)
        clickhouse_disk_total_bytes.labels(disk=disk).set(total_bytes)
        clickhouse_disk_free_ratio.labels(disk=disk).set(ratio)


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))
