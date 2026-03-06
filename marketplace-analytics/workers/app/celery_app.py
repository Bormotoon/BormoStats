"""Celery application definition."""

from __future__ import annotations

import os

from celery import Celery

from app.beat_schedule import beat_schedule
from common.env_validation import collect_worker_startup_issues, raise_for_issues

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

raise_for_issues("worker startup", collect_worker_startup_issues(os.environ))

celery_app = Celery(
    "marketplace_analytics",
    broker=REDIS_URL,
    include=[
        "app.tasks.wb_collect",
        "app.tasks.ozon_collect",
        "app.tasks.transforms",
        "app.tasks.marts",
        "app.tasks.maintenance",
    ],
)

celery_app.conf.update(
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    task_default_queue="etl",
    task_routes={
        "tasks.wb_collect.*": {"queue": "wb"},
        "tasks.ozon_collect.*": {"queue": "ozon"},
        "tasks.transforms.*": {"queue": "etl"},
        "tasks.marts.*": {"queue": "etl"},
        "tasks.maintenance.run_automation_rules": {"queue": "automation"},
        "tasks.maintenance.prune_old_raw": {"queue": "etl"},
    },
    beat_schedule=beat_schedule,
    timezone=os.getenv("TZ", "Europe/Warsaw"),
    enable_utc=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)
