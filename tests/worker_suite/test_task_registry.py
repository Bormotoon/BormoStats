"""Every scheduled/routed task must import cleanly and be consumable by a worker."""

from __future__ import annotations

import fnmatch
import importlib

import pytest
from app.beat_schedule import beat_schedule
from app.celery_app import celery_app

from common.celery_config import DEFAULT_TASK_QUEUE, TASK_QUEUES, TASK_ROUTES


@pytest.mark.parametrize("module", celery_app.conf.include)
def test_task_modules_import(module: str) -> None:
    importlib.import_module(module)


def _queue_for(task_name: str) -> str:
    for pattern, route in TASK_ROUTES.items():
        if fnmatch.fnmatch(task_name, pattern):
            return route["queue"]
    return DEFAULT_TASK_QUEUE


@pytest.mark.parametrize("entry", sorted(beat_schedule))
def test_scheduled_tasks_are_registered_and_consumed(entry: str) -> None:
    for module in celery_app.conf.include:
        importlib.import_module(module)
    task_name = beat_schedule[entry]["task"]
    assert task_name in celery_app.tasks, task_name
    assert _queue_for(task_name) in TASK_QUEUES


def test_worker_consumes_every_routed_queue() -> None:
    consumed = {queue.name for queue in celery_app.conf.task_queues}
    routed = {route["queue"] for route in TASK_ROUTES.values()} | {DEFAULT_TASK_QUEUE}
    assert routed <= consumed


def test_redeliveries_outlast_the_longest_retry_countdown() -> None:
    from common.webhooks import MAX_DELIVERY_ATTEMPTS, retry_delay_seconds

    longest = max(retry_delay_seconds(a) for a in range(1, MAX_DELIVERY_ATTEMPTS + 1))
    assert celery_app.conf.broker_transport_options["visibility_timeout"] > longest
    assert celery_app.conf.task_acks_late is True
