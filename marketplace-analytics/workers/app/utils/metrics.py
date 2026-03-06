"""Prometheus metrics helpers for worker tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from prometheus_client import Counter, Gauge, Histogram

ingestion_rows_total = Counter(
    "ingestion_rows_total",
    "Rows inserted by ingestion/transform tasks",
    ["table"],
)

task_runs_total = Counter(
    "task_runs_total",
    "Task runs by status",
    ["task_name", "status"],
)

task_duration_seconds = Histogram(
    "task_duration_seconds",
    "Task execution duration in seconds",
    ["task_name", "status"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)

watermark_lag_seconds = Gauge(
    "watermark_lag_seconds",
    "Current lag between now and watermark timestamp",
    ["source", "account_id"],
    multiprocess_mode="max",
)

empty_payload_total = Counter(
    "empty_payload_total",
    "Number of empty payload responses from collectors",
    ["source"],
)


def observe_rows(table: str, rows: int) -> None:
    if rows <= 0:
        return
    ingestion_rows_total.labels(table=table).inc(rows)


def observe_task(task_name: str, status: str, started_at: datetime, finished_at: datetime) -> None:
    start = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    end = finished_at if finished_at.tzinfo else finished_at.replace(tzinfo=UTC)
    duration = max(0.0, (end - start).total_seconds())
    task_runs_total.labels(task_name=task_name, status=status).inc()
    task_duration_seconds.labels(task_name=task_name, status=status).observe(duration)


def observe_watermark(source: str, account_id: str, watermark_ts: datetime) -> None:
    value = watermark_ts if watermark_ts.tzinfo else watermark_ts.replace(tzinfo=UTC)
    lag = max(0.0, (datetime.now(UTC) - value.astimezone(UTC)).total_seconds())
    watermark_lag_seconds.labels(source=source, account_id=account_id).set(lag)


def observe_empty_payload(source: str) -> None:
    empty_payload_total.labels(source=source).inc()
