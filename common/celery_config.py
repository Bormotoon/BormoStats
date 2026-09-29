"""Shared Celery routing configuration used by producers and workers."""

from __future__ import annotations

DEFAULT_TASK_QUEUE = "etl"

# Every queue a task can be routed to. Workers consume all of them unless started
# with ``-Q``/``WORKER_QUEUES`` (e.g. a dedicated worker for marketplace writes).
TASK_QUEUES: tuple[str, ...] = (
    "etl",
    "wb",
    "ozon",
    "competitor",
    "automation",
    "marketplace_actions",
    "webhooks",
)

TASK_ROUTES: dict[str, dict[str, str]] = {
    "tasks.wb_collect.*": {"queue": "wb"},
    "tasks.ozon_collect.*": {"queue": "ozon"},
    "tasks.competitor_collect.*": {"queue": "competitor"},
    "tasks.transforms.*": {"queue": "etl"},
    "tasks.marts.*": {"queue": "etl"},
    "tasks.maintenance.run_automation_rules": {"queue": "automation"},
    "tasks.maintenance.prune_old_raw": {"queue": "etl"},
    "tasks.insights.*": {"queue": "automation"},
    "tasks.bidder.*": {"queue": "marketplace_actions"},
    "tasks.repricer.*": {"queue": "marketplace_actions"},
    "tasks.webhooks.*": {"queue": "webhooks"},
    "tasks.exports.*": {"queue": "automation"},
}
