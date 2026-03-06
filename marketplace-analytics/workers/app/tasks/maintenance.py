"""Maintenance and automation tasks."""

from __future__ import annotations

import os
from pathlib import Path

import clickhouse_connect
import structlog
from app.utils.celery_helpers import shared_task
from app.utils.data_quality import evaluate_data_quality
from app.utils.runtime import log_task_run, new_run_context

from automation.actions.telegram import TelegramAction
from automation.engine import run_rules

LOGGER = structlog.get_logger(__name__)


def _ch_client() -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=os.getenv("CH_HOST", "localhost"),
        port=int(os.getenv("CH_PORT", "8123")),
        username=os.getenv("CH_USER", "default"),
        password=os.getenv("CH_PASSWORD", ""),
        database=os.getenv("CH_DB", "mp_analytics"),
        autogenerate_session_id=False,
    )


@shared_task(name="tasks.maintenance.run_automation_rules")
def run_automation_rules() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    rules_dir = root / "automation" / "rules"

    actions = {
        "telegram": TelegramAction(
            bot_token=os.getenv("TG_BOT_TOKEN", ""),
            chat_id=os.getenv("TG_CHAT_ID", ""),
        )
    }

    client = _ch_client()
    try:
        report = run_rules(client=client, rules_dir=rules_dir, actions=actions)
        return report
    finally:
        client.close()


@shared_task(name="tasks.maintenance.prune_old_raw")
def prune_old_raw(days: int = 120) -> dict[str, int]:
    keep_days = max(30, min(days, 3650))
    client = _ch_client()
    try:
        tables = [
            ("raw_wb_sales", "event_ts"),
            ("raw_wb_orders", "event_ts"),
            ("raw_wb_stocks", "snapshot_ts"),
            ("raw_wb_funnel_daily", "day"),
            ("raw_ozon_postings", "created_at"),
            ("raw_ozon_posting_items", "ingested_at"),
            ("raw_ozon_stocks", "snapshot_ts"),
            ("raw_ozon_ads_daily", "day"),
            ("raw_ozon_finance_ops", "operation_ts"),
        ]
        for table, column in tables:
            client.command(
                f"ALTER TABLE {table} DELETE WHERE {column} < now() - toIntervalDay(%(days)s)",
                parameters={"days": keep_days},
            )
        return {"retention_days": keep_days, "tables": len(tables)}
    finally:
        client.close()


@shared_task(name="tasks.maintenance.run_data_quality_checks")
def run_data_quality_checks() -> dict[str, object]:
    task_name = "tasks.maintenance.run_data_quality_checks"
    run_id, started_at = new_run_context(task_name)
    client = _ch_client()
    failure_logged = False

    try:
        issues = evaluate_data_quality(client)
        report: dict[str, object] = {
            "status": "failed" if issues else "success",
            "issue_count": len(issues),
            "issues": [issue.as_meta() for issue in issues],
        }
        if issues:
            for issue in issues:
                LOGGER.warning(
                    "data_quality_issue_detected",
                    check=issue.check,
                    failures=issue.failures,
                    summary=issue.summary,
                    samples=issue.samples,
                )
            summary = "; ".join(f"{issue.check}={issue.failures}" for issue in issues)
            log_task_run(
                client,
                task_name,
                run_id,
                started_at,
                "failed",
                0,
                f"data quality failures detected: {summary}",
                meta=report,
            )
            failure_logged = True
            raise RuntimeError(summary)

        log_task_run(
            client,
            task_name,
            run_id,
            started_at,
            "success",
            0,
            "data quality checks passed",
            meta=report,
        )
        return report
    except Exception as exc:
        if not failure_logged:
            log_task_run(
                client,
                task_name,
                run_id,
                started_at,
                "failed",
                0,
                str(exc),
                meta={"status": "failed", "issue_count": 0, "issues": []},
            )
        raise
    finally:
        client.close()
