"""Maintenance and automation tasks."""

from __future__ import annotations

import os
from pathlib import Path

import clickhouse_connect
from app.utils.celery_helpers import shared_task

from automation.actions.telegram import TelegramAction
from automation.engine import run_rules


def _ch_client() -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=os.getenv("CH_HOST", "localhost"),
        port=int(os.getenv("CH_PORT", "8123")),
        username=os.getenv("CH_USER", "default"),
        password=os.getenv("CH_PASSWORD", ""),
        database=os.getenv("CH_DB", "mp_analytics"),
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
