"""Emit webhook events from worker tasks (fan-out happens in tasks.webhooks)."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from celery import current_app

LOGGER = structlog.get_logger(__name__)
DISPATCH_TASK = "tasks.webhooks.dispatch_event"


def emit_event(organization_id: str, event_type: str, payload: dict[str, Any]) -> None:
    try:
        current_app.send_task(
            DISPATCH_TASK,
            kwargs={
                "organization_id": organization_id,
                "event_type": event_type,
                "payload": payload,
                "event_id": str(uuid.uuid4()),
            },
            ignore_result=True,
        )
    except Exception as exc:
        LOGGER.warning("webhook_event_enqueue_failed", event_type=event_type, error=str(exc))
