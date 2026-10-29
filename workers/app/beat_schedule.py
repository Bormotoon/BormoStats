"""Periodic Celery Beat schedule."""

from __future__ import annotations

from celery.schedules import crontab

beat_schedule = {
    "daily_reports": {
        "task": "tasks.reports.collect_daily",
        "schedule": crontab(minute="0", hour="6"),
    },
    "automation_rules_run": {
        "task": "tasks.maintenance.run_automation_rules",
        "schedule": crontab(minute="0", hour="9,15,21"),
    },
    "maintenance_prune_raw": {
        "task": "tasks.maintenance.prune_old_raw",
        "schedule": crontab(minute="0", hour="2"),
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
    "insights_daily_digest": {
        "task": "tasks.insights.send_daily_digest",
        "schedule": crontab(minute="30", hour="7"),
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
