"""Operational Prometheus metrics gathered from Redis and ClickHouse.

Collection runs in a background thread (:class:`OperationalMetricsRefresher`), so a
Prometheus scrape of ``/metrics`` only serializes already-computed gauges.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any, cast

import structlog
from app.core.config import Settings
from app.db.ch import build_client
from prometheus_client import Gauge
from redis import Redis

LOGGER = structlog.get_logger(__name__)

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
        redis_client = Redis.from_url(
            settings.authenticated_redis_url, socket_timeout=3, socket_connect_timeout=3
        )
        try:
            redis_client.ping()
            memory_info = cast(Mapping[str, Any], redis_client.info(section="memory"))
        finally:
            redis_client.close()
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
    except Exception:
        _mark_clickhouse_down()
        return
    try:
        try:
            client.query("SELECT 1")
        except Exception:
            _mark_clickhouse_down()
            return
        service_readiness.labels(service="clickhouse").set(1)
        try:
            rows = client.query(
                "SELECT name, free_space, total_space FROM system.disks"
            ).result_rows
        except Exception as exc:
            # Missing grant or transient error: ClickHouse is still ready.
            LOGGER.warning("clickhouse_disk_metrics_unavailable", error=str(exc)[:300])
            return
    finally:
        client.close()

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


def _mark_clickhouse_down() -> None:
    service_readiness.labels(service="clickhouse").set(0)
    clickhouse_disk_free_bytes.clear()
    clickhouse_disk_total_bytes.clear()
    clickhouse_disk_free_ratio.clear()


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


class OperationalMetricsRefresher:
    """Refresh operational gauges every ``interval`` seconds in a daemon thread."""

    def __init__(self, settings: Settings, interval_seconds: float) -> None:
        self._settings = settings
        self._interval = max(5.0, interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="ops-metrics-refresher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                refresh_operational_metrics(self._settings)
            except Exception as exc:
                LOGGER.warning("ops_metrics_refresh_failed", error=str(exc))
            self._stop.wait(self._interval)
