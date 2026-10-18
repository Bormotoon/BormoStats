"""Periodic Celery Beat schedule."""

from __future__ import annotations

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
        # Ozon sales come from the realization accruals: hourly keeps them as fresh as WB
        # (a run reads the last 3 days, one request per day)
        "schedule": crontab(minute="50"),
    },
    # finance block: the seller cabinet's balance, payouts and every charge
    "ozon_finance_balance": {
        "task": "tasks.ozon_collect.ozon_finance_balance",
        "schedule": crontab(minute="52"),
    },
    "wb_finance_report": {
        "task": "tasks.wb_collect.wb_finance_report",
        "schedule": crontab(minute="17"),
    },
    "wb_balance_snapshot": {
        "task": "tasks.wb_collect.wb_balance_snapshot",
        "schedule": crontab(minute="19"),
    },
    "ozon_ads_daily": {
        "task": "tasks.ozon_collect.ozon_ads_daily",
        "schedule": crontab(minute="40", hour="*/6"),
    },
    "transform_raw_to_stg": {
        "task": "tasks.transforms.transform_all_recent",
        "schedule": crontab(minute="5,35"),
    },
    "build_marts_recent": {
        "task": "tasks.marts.build_marts_recent",
        "schedule": crontab(minute="20,50"),
    },
    "build_marts_backfill_14d": {
        "task": "tasks.marts.build_marts_backfill_days",
        "schedule": crontab(minute="20", hour="4"),
    },
    "automation_rules_run": {
        "task": "tasks.maintenance.run_automation_rules",
        "schedule": crontab(minute="0", hour="9,15,21"),
    },
    "maintenance_prune_raw": {
        "task": "tasks.maintenance.prune_old_raw",
        "schedule": crontab(minute="0", hour="2"),
    },
    "maintenance_data_quality": {
        "task": "tasks.maintenance.run_data_quality_checks",
        "schedule": crontab(minute="58", hour="*"),
    },
    "competitor_wb_product_cards": {
        "task": "tasks.competitor_collect.wb_product_cards",
        "schedule": crontab(minute="15", hour="*/1"),
    },
    "competitor_wb_search_results": {
        "task": "tasks.competitor_collect.wb_search_results",
        "schedule": crontab(minute="30", hour="*/2"),
    },
    "competitor_ozon_product_cards": {
        "task": "tasks.competitor_collect.ozon_product_cards",
        "schedule": crontab(minute="25", hour="*/1"),
    },
    "competitor_build_marts": {
        "task": "tasks.competitor_collect.build_marts",
        "schedule": crontab(minute="45", hour="*/1"),
    },
    "bidder_evaluate_rules": {
        "task": "tasks.bidder.bidder_evaluate_rules",
        "schedule": crontab(minute="*/5"),
    },
    "repricer_evaluate_rules": {
        "task": "tasks.repricer.repricer_evaluate_rules",
        "schedule": crontab(minute="*/10"),
    },
    # reviews and the auto replies to reviews without text
    "reviews_sync": {
        "task": "tasks.reviews.sync_reviews",
        "schedule": crontab(minute="7,22,37,52"),
    },
    "insights_generate_tasks": {
        "task": "tasks.insights.generate_actionable_tasks",
        "schedule": crontab(minute="0", hour="6"),
    },
    "insights_daily_digest": {
        "task": "tasks.insights.send_daily_digest",
        "schedule": crontab(minute="30", hour="7"),
    },
    "history_wb_catalog": {
        "task": "tasks.history.wb_catalog_snapshot",
        "schedule": crontab(minute="12", hour="*/1"),
    },
    "history_ozon_catalog": {
        "task": "tasks.history.ozon_catalog_snapshot",
        "schedule": crontab(minute="27", hour="*/1"),
    },
    # must finish before maintenance_prune_raw (02:00) may delete anything
    "history_backfill_raw": {
        "task": "tasks.history.backfill_raw_archive",
        "schedule": crontab(minute="30", hour="1"),
    },
    "exports_prune": {
        "task": "tasks.exports.prune_exports",
        "schedule": crontab(minute="40", hour="2"),
    },
}
