"""Periodic Celery Beat schedule."""

from celery.schedules import crontab

beat_schedule = {
    "wb_sales_incremental": {
        "task": "tasks.wb_collect.wb_sales_incremental",
        "schedule": crontab(minute="*/15"),
    },
    "wb_orders_incremental": {
        "task": "tasks.wb_collect.wb_orders_incremental",
        "schedule": crontab(minute="*/15"),
    },
    "wb_stocks_snapshot": {
        "task": "tasks.wb_collect.wb_stocks_snapshot",
        "schedule": crontab(minute="*/30"),
    },
    "wb_funnel_roll": {
        "task": "tasks.wb_collect.wb_funnel_roll",
        "schedule": crontab(minute="5", hour="*/1"),
    },
    "wb_sales_backfill_14d": {
        "task": "tasks.wb_collect.wb_sales_backfill_days",
        "schedule": crontab(minute="10", hour="3"),
    },
    "wb_orders_backfill_14d": {
        "task": "tasks.wb_collect.wb_orders_backfill_days",
        "schedule": crontab(minute="20", hour="3"),
    },
    "wb_funnel_backfill_14d": {
        "task": "tasks.wb_collect.wb_funnel_backfill_days",
        "schedule": crontab(minute="30", hour="3"),
    },
    "ozon_postings_incremental": {
        "task": "tasks.ozon_collect.ozon_postings_incremental",
        "schedule": crontab(minute="*/20"),
    },
    "ozon_stocks_snapshot": {
        "task": "tasks.ozon_collect.ozon_stocks_snapshot",
        "schedule": crontab(minute="*/30"),
    },
    "ozon_finance_incremental": {
        "task": "tasks.ozon_collect.ozon_finance_incremental",
        "schedule": crontab(minute="50", hour="*/6"),
    },
    "ozon_ads_daily": {
        "task": "tasks.ozon_collect.ozon_ads_daily",
        "schedule": crontab(minute="40", hour="*/6"),
    },
    "transform_raw_to_stg": {
        "task": "tasks.transforms.transform_all_recent",
        "schedule": crontab(minute="*/30"),
    },
    "build_marts_recent": {
        "task": "tasks.marts.build_marts_recent",
        "schedule": crontab(minute="0", hour="*/1"),
    },
    "build_marts_backfill_14d": {
        "task": "tasks.marts.build_marts_backfill_days",
        "schedule": crontab(minute="0", hour="4"),
    },
    "automation_rules_run": {
        "task": "tasks.maintenance.run_automation_rules",
        "schedule": crontab(minute="0", hour="9,15,21"),
    },
    "maintenance_prune_raw": {
        "task": "tasks.maintenance.prune_old_raw",
        "schedule": crontab(minute="0", hour="2"),
    },
}
