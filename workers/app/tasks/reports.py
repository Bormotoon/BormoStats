"""One daily collection pass, followed by dependent analytics rebuilds."""

from __future__ import annotations

import json
from datetime import datetime
from importlib import import_module
from typing import Any
from zoneinfo import ZoneInfo

from app.utils.celery_helpers import shared_task
from app.utils.locking import LockNotAcquiredError, lock_scope
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context

TASK_NAME = "tasks.reports.collect_daily"
REPORT_TIMEZONE = "Europe/Moscow"
CHECKPOINT_TTL = 7 * 86400

# A single entry per source. WB sales/orders use last-change watermarks rather
# than overlapping historical requests. SKU advertising depends on finance rows.
# Rebuild 90 days too: posting status corrections must reach stg_orders.
REPORT_STEPS: tuple[tuple[str, tuple[Any, ...]], ...] = (
    ("tasks.history.wb_catalog_snapshot", ()),
    ("tasks.history.ozon_catalog_snapshot", ()),
    ("tasks.wb_collect.wb_sales_incremental", ()),
    ("tasks.wb_collect.wb_orders_incremental", ()),
    ("tasks.wb_collect.wb_stocks_snapshot", ()),
    ("tasks.wb_collect.wb_funnel_backfill_days", (14,)),
    ("tasks.wb_collect.wb_finance_report", ()),
    ("tasks.wb_collect.wb_balance_snapshot", ()),
    ("tasks.ozon_collect.ozon_postings_incremental", ()),
    ("tasks.ozon_collect.ozon_stocks_snapshot", ()),
    ("tasks.ozon_collect.ozon_finance_incremental", ()),
    ("tasks.ozon_collect.ozon_finance_balance", ()),
    ("tasks.ozon_collect.ozon_buyouts_week", (7,)),
    ("tasks.ozon_collect.ozon_realization_backfill_days", (62,)),
    ("tasks.ozon_collect.ozon_ads_daily", ()),
    ("tasks.ozon_collect.ozon_ads_sku_backfill_days", (3,)),
    ("tasks.transforms.transform_backfill_days", (90,)),
    ("tasks.marts.build_marts_backfill_days", (90,)),
    ("tasks.maintenance.run_data_quality_checks", ()),
    ("tasks.insights.generate_actionable_tasks", ()),
)


def _call_step(task_name: str, args: tuple[Any, ...]) -> dict[str, Any]:
    module_name, function = task_name.rsplit(".", 1)
    task = getattr(import_module(f"app.{module_name}"), function)
    return task(*args)


def _run_daily(run_day: str) -> dict[str, Any]:
    redis_client = get_redis_client()
    client = get_ch_client()
    run_id, started_at = new_run_context()
    key = f"reports:daily:v1:{run_day}"
    results: dict[str, Any] = {}
    step = ""
    try:
        with lock_scope(
            redis_client=redis_client,
            source="daily_reports",
            account_id="global",
            ttl_seconds=600,
            auto_renew=True,
        ) as lock:
            if redis_client.hget(key, "completed"):
                return {"status": "skipped", "reason": "already_completed", "day": run_day}
            for step, args in REPORT_STEPS:
                lock.ensure_held()
                saved = redis_client.hget(key, step)
                if saved:
                    results[step] = json.loads(saved)
                    continue
                result = _call_step(step, args)
                lock.ensure_held()
                status = result.get("status")
                # Source tasks may be disabled by configuration/capability. A
                # rebuild skipped due to a busy lock is never a completed step.
                if result.get("reason") == "lock_not_acquired":
                    raise LockNotAcquiredError(f"daily report step busy: {step}")
                if status not in {"success", "passed", "skipped"}:
                    raise RuntimeError(f"daily report step failed: {step}: {result}")
                if status == "skipped" and not step.startswith(
                    ("tasks.wb_collect.", "tasks.ozon_collect.", "tasks.history.")
                ):
                    raise RuntimeError(f"dependent report step skipped: {step}: {result}")
                results[step] = result
                redis_client.hset(key, step, json.dumps(result, default=str))
                redis_client.expire(key, CHECKPOINT_TTL)
            lock.ensure_held()
            log_task_run(
                client,
                TASK_NAME,
                run_id,
                started_at,
                "success",
                0,
                "Daily reports collected and rebuilt",
                meta={"day": run_day, "steps": results},
            )
            redis_client.hset(key, "completed", run_id)
            redis_client.expire(key, CHECKPOINT_TTL)
        return {"status": "success", "day": run_day, "steps": results}
    except Exception as exc:
        log_task_run(
            client,
            TASK_NAME,
            run_id,
            started_at,
            "failed",
            0,
            str(exc),
            meta={"day": run_day, "failed_step": step, "completed_steps": list(results)},
        )
        raise


@shared_task(name=TASK_NAME, bind=True, max_retries=5)
def collect_daily(self: Any, run_day: str | None = None) -> dict[str, Any]:
    day = run_day or datetime.now(ZoneInfo(REPORT_TIMEZONE)).date().isoformat()
    try:
        return _run_daily(day)
    except Exception as exc:
        # Persist the date across retries, including a retry crossing midnight.
        raise self.retry(exc=exc, countdown=300, kwargs={"run_day": day}) from exc
