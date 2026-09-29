"""Celery producer shared by API handlers (one broker connection pool per process)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import Settings
from app.core.observability import current_request_id
from celery import Celery

from common.celery_config import DEFAULT_TASK_QUEUE, TASK_ROUTES


@lru_cache(maxsize=4)
def _producer(broker_url: str) -> Celery:
    celery = Celery("backend-producer", broker=broker_url)
    celery.conf.update(
        broker_url=broker_url,
        task_default_queue=DEFAULT_TASK_QUEUE,
        task_routes=TASK_ROUTES,
        task_ignore_result=True,
        broker_connection_retry_on_startup=True,
    )
    return celery


def get_producer(settings: Settings) -> Celery:
    return _producer(settings.authenticated_redis_url)


def send_task(
    settings: Settings,
    task_name: str,
    *,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> str:
    merged_headers = dict(headers or {})
    request_id = current_request_id()
    if request_id:
        merged_headers.setdefault("request_id", request_id)
    result = get_producer(settings).send_task(
        task_name, args=args, kwargs=kwargs, ignore_result=True, headers=merged_headers
    )
    return str(result.id)
