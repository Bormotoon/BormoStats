"""Service layer for admin operations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import clickhouse_connect
from celery import Celery

from app.core.config import Settings
from app.db.ch import query_dicts

_QUERIES_DIR = Path(__file__).resolve().parents[1] / "db" / "queries"


def _load_sql(name: str) -> str:
    return (_QUERIES_DIR / name).read_text(encoding="utf-8")


class AdminService:
    def __init__(self, client: clickhouse_connect.driver.Client, settings: Settings) -> None:
        self.client = client
        self.celery = Celery("backend-admin", broker=settings.redis_url)

    def watermarks(self) -> list[dict[str, Any]]:
        return query_dicts(self.client, _load_sql("admin_watermarks.sql"))

    def task_runs(self, limit: int) -> list[dict[str, Any]]:
        return query_dicts(self.client, _load_sql("admin_task_runs.sql"), {"limit": limit})

    def run_task(self, task_name: str, args: list[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
        async_result = self.celery.send_task(task_name, args=args, kwargs=kwargs)
        return {
            "task_name": task_name,
            "task_id": async_result.id,
            "queued_at": datetime.now(UTC).isoformat(),
        }

    def backfill(self, marketplace: str, dataset: str, days: int) -> dict[str, Any]:
        mapping = {
            ("wb", "sales"): "tasks.wb_collect.wb_sales_backfill_days",
            ("wb", "orders"): "tasks.wb_collect.wb_orders_backfill_days",
            ("wb", "funnel"): "tasks.wb_collect.wb_funnel_backfill_days",
            ("ozon", "postings"): "tasks.ozon_collect.ozon_postings_backfill_days",
            ("marts", "build"): "tasks.marts.build_marts_backfill_days",
        }
        task_name = mapping.get((marketplace, dataset))
        if task_name is None:
            raise ValueError(f"unsupported backfill target: {marketplace}:{dataset}")
        return self.run_task(task_name=task_name, args=[days], kwargs={})
