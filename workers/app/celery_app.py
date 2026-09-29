"""Celery application definition."""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any

import structlog
from app.utils.metrics_export import (
    configure_metrics_runtime,
    detect_metrics_role,
    mark_worker_process_dead,
    start_metrics_http_server,
)
from celery import Celery
from celery.signals import before_task_publish, task_postrun, task_prerun, worker_process_shutdown
from kombu import Queue

from common.celery_config import DEFAULT_TASK_QUEUE, TASK_QUEUES, TASK_ROUTES
from common.env_validation import collect_worker_startup_issues, raise_for_issues
from common.file_secrets import load_file_secrets
from common.redis_url import build_redis_url

load_file_secrets()

REDIS_URL = build_redis_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    os.getenv("REDIS_PASSWORD", ""),
    os.getenv("REDIS_USERNAME", ""),
)
METRICS_ROLE = detect_metrics_role()
# Longest webhook retry countdown is one hour; Redis must not re-deliver ETA tasks early.
VISIBILITY_TIMEOUT_SECONDS = 2 * 3600

configure_metrics_runtime(METRICS_ROLE)
beat_schedule = import_module("app.beat_schedule").beat_schedule

raise_for_issues("worker startup", collect_worker_startup_issues(os.environ))

celery_app = Celery(
    "marketplace_analytics",
    broker=REDIS_URL,
    include=[
        "app.tasks.wb_collect",
        "app.tasks.ozon_collect",
        "app.tasks.competitor_collect",
        "app.tasks.transforms",
        "app.tasks.marts",
        "app.tasks.maintenance",
        "app.tasks.bidder",
        "app.tasks.repricer",
        "app.tasks.insights",
        "app.tasks.webhooks",
        "app.tasks.exports",
    ],
)

celery_app.conf.update(
    broker_url=REDIS_URL,
    broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_SECONDS},
    task_default_queue=DEFAULT_TASK_QUEUE,
    task_queues=[Queue(name) for name in TASK_QUEUES],
    task_ignore_result=True,
    task_routes=TASK_ROUTES,
    # Tasks are idempotent (watermarks, dedupe keys), so a task interrupted by a
    # worker crash or a non-graceful shutdown is re-delivered instead of lost.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    beat_schedule=beat_schedule,
    timezone=os.getenv("TZ", "Europe/Warsaw"),
    enable_utc=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

_METRICS_SERVER = start_metrics_http_server(METRICS_ROLE)


def _handle_worker_process_shutdown(pid: int | None = None, **_: object) -> None:
    mark_worker_process_dead(pid)


def _propagate_request_id(headers: dict[str, Any] | None = None, **_: object) -> None:
    """Copy the current request/correlation id into outgoing task headers."""
    if headers is None or headers.get("request_id"):
        return
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id:
        headers["request_id"] = request_id


def _bind_task_context(task_id: str | None = None, task: Any = None, **_: object) -> None:
    request = getattr(task, "request", None)
    request_id = getattr(request, "request_id", None) or task_id
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        task_id=task_id,
        task_name=getattr(task, "name", None),
    )


def _clear_task_context(**_: object) -> None:
    structlog.contextvars.clear_contextvars()


worker_process_shutdown.connect(_handle_worker_process_shutdown)
before_task_publish.connect(_propagate_request_id)
task_prerun.connect(_bind_task_context)
task_postrun.connect(_clear_task_context)
