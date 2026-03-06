"""Service layer for admin operations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import clickhouse_connect
import structlog
from app.core.config import Settings
from app.db.ch import query_dicts
from app.models.admin import (
    ActionQueueResponse,
    AdminRequestContext,
    BackfillRequest,
    BuildMartsBackfillRequest,
    BuildMartsRecentRequest,
    PruneOldRawRequest,
    RunAutomationRulesRequest,
    TransformBackfillRequest,
    TransformRecentRequest,
)
from celery import Celery

_QUERIES_DIR = Path(__file__).resolve().parents[1] / "db" / "queries"
LOGGER = structlog.get_logger(__name__)


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

    def audit_read(
        self,
        *,
        action: str,
        audit: AdminRequestContext,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._log_audit(event="admin_read", action=action, audit=audit, details=details or {})

    def _log_audit(
        self,
        *,
        event: str,
        action: str,
        audit: AdminRequestContext,
        details: dict[str, Any],
    ) -> None:
        LOGGER.info(
            event,
            action=action,
            path=audit.path,
            method=audit.method,
            remote_addr=audit.remote_addr,
            forwarded_for=audit.forwarded_for,
            user_agent=audit.user_agent,
            details=details,
        )

    def _queue_task(
        self,
        *,
        action: str,
        task_name: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        audit: AdminRequestContext,
        parameters: dict[str, Any] | None = None,
    ) -> ActionQueueResponse:
        async_result = self.celery.send_task(task_name, args=args, kwargs=kwargs)
        payload = ActionQueueResponse(
            action=action,
            task_name=task_name,
            task_id=async_result.id,
            queued_at=datetime.now(UTC).isoformat(),
            parameters=parameters or {},
        )
        self._log_audit(
            event="admin_action_queued",
            action=action,
            audit=audit,
            details=payload.model_dump(mode="json"),
        )
        return payload

    def queue_backfill(
        self,
        payload: BackfillRequest,
        audit: AdminRequestContext,
    ) -> ActionQueueResponse:
        mapping = {
            ("wb", "sales"): "tasks.wb_collect.wb_sales_backfill_days",
            ("wb", "orders"): "tasks.wb_collect.wb_orders_backfill_days",
            ("wb", "funnel"): "tasks.wb_collect.wb_funnel_backfill_days",
            ("ozon", "postings"): "tasks.ozon_collect.ozon_postings_backfill_days",
            ("ozon", "finance"): "tasks.ozon_collect.ozon_finance_backfill_days",
            ("marts", "build"): "tasks.marts.build_marts_backfill_days",
        }
        task_name = mapping[(payload.marketplace.value, payload.dataset.value)]
        return self._queue_task(
            action="backfill",
            task_name=task_name,
            args=[payload.days],
            kwargs={},
            audit=audit,
            parameters=payload.model_dump(mode="json"),
        )

    def queue_transform_recent(
        self,
        _: TransformRecentRequest,
        audit: AdminRequestContext,
    ) -> ActionQueueResponse:
        return self._queue_task(
            action="transform_recent",
            task_name="tasks.transforms.transform_all_recent",
            args=[],
            kwargs={},
            audit=audit,
        )

    def queue_transform_backfill(
        self,
        payload: TransformBackfillRequest,
        audit: AdminRequestContext,
    ) -> ActionQueueResponse:
        return self._queue_task(
            action="transform_backfill",
            task_name="tasks.transforms.transform_backfill_days",
            args=[payload.days],
            kwargs={},
            audit=audit,
            parameters=payload.model_dump(mode="json"),
        )

    def queue_marts_recent(
        self,
        _: BuildMartsRecentRequest,
        audit: AdminRequestContext,
    ) -> ActionQueueResponse:
        return self._queue_task(
            action="marts_recent",
            task_name="tasks.marts.build_marts_recent",
            args=[],
            kwargs={},
            audit=audit,
        )

    def queue_marts_backfill(
        self,
        payload: BuildMartsBackfillRequest,
        audit: AdminRequestContext,
    ) -> ActionQueueResponse:
        return self._queue_task(
            action="marts_backfill",
            task_name="tasks.marts.build_marts_backfill_days",
            args=[payload.days],
            kwargs={},
            audit=audit,
            parameters=payload.model_dump(mode="json"),
        )

    def queue_run_automation_rules(
        self,
        _: RunAutomationRulesRequest,
        audit: AdminRequestContext,
    ) -> ActionQueueResponse:
        return self._queue_task(
            action="run_automation_rules",
            task_name="tasks.maintenance.run_automation_rules",
            args=[],
            kwargs={},
            audit=audit,
        )

    def queue_prune_old_raw(
        self,
        payload: PruneOldRawRequest,
        audit: AdminRequestContext,
    ) -> ActionQueueResponse:
        return self._queue_task(
            action="prune_old_raw",
            task_name="tasks.maintenance.prune_old_raw",
            args=[payload.days],
            kwargs={},
            audit=audit,
            parameters=payload.model_dump(mode="json"),
        )
