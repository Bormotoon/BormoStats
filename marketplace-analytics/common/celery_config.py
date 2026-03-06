"""Shared Celery routing configuration used by producers and workers."""

from __future__ import annotations

DEFAULT_TASK_QUEUE = "etl"

TASK_ROUTES: dict[str, dict[str, str]] = {
    "tasks.wb_collect.*": {"queue": "wb"},
    "tasks.ozon_collect.*": {"queue": "ozon"},
    "tasks.transforms.*": {"queue": "etl"},
    "tasks.marts.*": {"queue": "etl"},
    "tasks.maintenance.run_automation_rules": {"queue": "automation"},
    "tasks.maintenance.prune_old_raw": {"queue": "etl"},
}
