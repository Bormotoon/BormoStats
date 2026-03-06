"""Celery application definition."""

from __future__ import annotations

import os
from importlib import import_module

from app.utils.metrics_export import (
    configure_metrics_runtime,
    detect_metrics_role,
    mark_worker_process_dead,
    start_metrics_http_server,
)
from celery import Celery
from celery.signals import worker_process_shutdown

from common.env_validation import collect_worker_startup_issues, raise_for_issues

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
METRICS_ROLE = detect_metrics_role()

configure_metrics_runtime(METRICS_ROLE)
beat_schedule = import_module("app.beat_schedule").beat_schedule

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

_METRICS_SERVER = start_metrics_http_server(METRICS_ROLE)


def _handle_worker_process_shutdown(pid: int | None = None, **_: object) -> None:
    mark_worker_process_dead(pid)


worker_process_shutdown.connect(_handle_worker_process_shutdown)
