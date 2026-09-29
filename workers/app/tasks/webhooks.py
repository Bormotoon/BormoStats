"""Webhook delivery engine.

``dispatch_event`` fans an event out to the organization's active subscriptions;
``deliver_to_subscription`` performs one signed HTTP attempt and re-schedules
itself with exponential backoff until ``MAX_DELIVERY_ATTEMPTS``, after which the
delivery is logged as ``dead_letter``.

Security:
* the target URL is re-validated on every attempt (SSRF: private, loopback and
  link-local addresses are refused) and the connection is pinned to the
  validated IP, so DNS rebinding cannot redirect it; redirects are not followed;
* payloads are signed with HMAC-SHA256 over ``"{timestamp}.{body}"`` and carry the
  event id as ``Idempotency-Key`` so receivers can reject replays and duplicates.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import structlog
from app.utils.celery_helpers import shared_task
from app.utils.metrics import observe_webhook_delivery
from app.utils.runtime import get_ch_client
from celery import current_app
from clickhouse_connect.driver import Client

from common.secret_box import SecretBoxError, decrypt_secret
from common.sql import insert_values_sql
from common.url_safety import UnsafeUrlError, validate_outbound_url
from common.webhooks import (
    MAX_DELIVERY_ATTEMPTS,
    compute_signature,
    retry_delay_seconds,
    subscription_matches,
)

LOGGER = structlog.get_logger(__name__)
DISPATCH_TASK = "tasks.webhooks.dispatch_event"
DELIVER_TASK = "tasks.webhooks.deliver_to_subscription"
REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_BODY_LOG_LIMIT = 2000

_LOG_INSERT = insert_values_sql(
    "webhook_logs",
    (
        ("log_id", "String"),
        ("organization_id", "String"),
        ("subscription_id", "Nullable(String)"),
        ("event_id", "String"),
        ("event_type", "String"),
        ("attempt", "UInt8"),
        ("status", "String"),
        ("request_body", "String"),
        ("response_body", "String"),
        ("response_status", "UInt16"),
        ("success", "UInt8"),
        ("duration_ms", "UInt32"),
        ("next_retry_at", "Nullable(DateTime)"),
        ("created_at", "DateTime"),
    ),
)


@dataclass(frozen=True)
class Subscription:
    subscription_id: str
    organization_id: str
    endpoint_url: str
    encrypted_secret: str
    events: list[str]
    is_active: bool


@dataclass(frozen=True)
class DeliveryOutcome:
    status: str
    response_status: int = 0
    response_body: str = ""
    duration_ms: int = 0

    @property
    def success(self) -> bool:
        return self.status == "delivered"

    @property
    def retryable(self) -> bool:
        return self.status == "failed"


def _allow_private_targets() -> bool:
    return os.getenv("WEBHOOK_ALLOW_PRIVATE_TARGETS", "").strip().casefold() in {
        "1",
        "true",
        "yes",
    }


def load_subscriptions(
    client: Client, organization_id: str, subscription_id: str | None = None
) -> list[Subscription]:
    clause = " AND subscription_id = {sid:String}" if subscription_id else ""
    rows = client.query(
        "SELECT subscription_id, organization_id, endpoint_url, secret, events, is_active"
        " FROM webhook_subscriptions FINAL WHERE organization_id = {oid:String}" + clause,
        parameters={"oid": organization_id, "sid": subscription_id or ""},
    )
    return [
        Subscription(
            subscription_id=str(r["subscription_id"]),
            organization_id=str(r["organization_id"]),
            endpoint_url=str(r["endpoint_url"]),
            encrypted_secret=str(r.get("secret") or ""),
            events=[str(e) for e in (r.get("events") or [])],
            is_active=bool(r.get("is_active", 1)),
        )
        for r in rows.named_results()
    ]


def build_body(
    event_id: str, event_type: str, organization_id: str, payload: dict[str, Any]
) -> bytes:
    envelope = {
        "id": event_id,
        "type": event_type,
        "organization_id": organization_id,
        "created_at": datetime.now(UTC).isoformat(),
        "data": payload,
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=str).encode()


def _pinned_request(url: str, address: str) -> tuple[str, str, dict[str, Any]]:
    """Rewrite ``url`` to connect to the validated IP while keeping Host/SNI."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    ip_host = f"[{address}]" if ":" in address else address
    netloc = ip_host if parts.port is None else f"{ip_host}:{parts.port}"
    pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    host_header = host if parts.port is None else f"{host}:{parts.port}"
    extensions: dict[str, Any] = {"sni_hostname": host} if parts.scheme == "https" else {}
    return pinned, host_header, extensions


def send_signed(
    subscription: Subscription,
    secret: str,
    event_id: str,
    event_type: str,
    body: bytes,
    *,
    transport: httpx.BaseTransport | None = None,
) -> DeliveryOutcome:
    try:
        target = validate_outbound_url(
            subscription.endpoint_url, allow_private=_allow_private_targets()
        )
    except UnsafeUrlError as exc:
        return DeliveryOutcome(status="blocked", response_body=str(exc))

    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BormoStats-Webhooks/1",
        "X-BormoStats-Event": event_type,
        "X-BormoStats-Event-Id": event_id,
        "X-BormoStats-Timestamp": str(timestamp),
        "X-BormoStats-Signature": compute_signature(secret, timestamp, body),
        "Idempotency-Key": event_id,
    }
    url = target.url
    extensions: dict[str, Any] = {}
    if target.addresses:
        url, headers["Host"], extensions = _pinned_request(target.url, target.addresses[0])

    started = time.perf_counter()
    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT, follow_redirects=False, transport=transport
        ) as http:
            response = http.post(url, content=body, headers=headers, extensions=extensions)
    except httpx.HTTPError as exc:
        return DeliveryOutcome(
            status="failed",
            response_body=f"{type(exc).__name__}: {exc}"[:_BODY_LOG_LIMIT],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    duration_ms = int((time.perf_counter() - started) * 1000)
    status = "delivered" if 200 <= response.status_code < 300 else "failed"
    return DeliveryOutcome(
        status=status,
        response_status=response.status_code,
        response_body=response.text[:_BODY_LOG_LIMIT],
        duration_ms=duration_ms,
    )


def _log_attempt(
    client: Client,
    subscription: Subscription | None,
    organization_id: str,
    event_id: str,
    event_type: str,
    attempt: int,
    outcome: DeliveryOutcome,
    body: bytes,
    next_retry_at: datetime | None,
) -> None:
    client.command(
        _LOG_INSERT,
        parameters={
            "log_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "subscription_id": subscription.subscription_id if subscription else None,
            "event_id": event_id,
            "event_type": event_type,
            "attempt": attempt,
            "status": outcome.status,
            "request_body": body.decode("utf-8", errors="replace")[:_BODY_LOG_LIMIT],
            "response_body": outcome.response_body,
            "response_status": outcome.response_status,
            "success": 1 if outcome.success else 0,
            "duration_ms": outcome.duration_ms,
            "next_retry_at": next_retry_at,
            "created_at": datetime.now(UTC).replace(microsecond=0),
        },
    )
    observe_webhook_delivery(outcome.status)


@shared_task(name=DISPATCH_TASK)
def dispatch_event(
    organization_id: str,
    event_type: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> dict[str, object]:
    client = get_ch_client()
    event_id = event_id or str(uuid.uuid4())
    queued = 0
    for subscription in load_subscriptions(client, organization_id):
        if not subscription.is_active or not subscription_matches(subscription.events, event_type):
            continue
        current_app.send_task(
            DELIVER_TASK,
            kwargs={
                "organization_id": organization_id,
                "subscription_id": subscription.subscription_id,
                "event_id": event_id,
                "event_type": event_type,
                "payload": payload,
                "attempt": 1,
            },
            ignore_result=True,
        )
        queued += 1
    return {"event_id": event_id, "queued": queued}


@shared_task(name=DELIVER_TASK)
def deliver_to_subscription(
    organization_id: str,
    subscription_id: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    attempt: int = 1,
) -> dict[str, object]:
    client = get_ch_client()
    body = build_body(event_id, event_type, organization_id, payload)
    subscriptions = load_subscriptions(client, organization_id, subscription_id)
    subscription = subscriptions[0] if subscriptions else None

    if subscription is None or not subscription.is_active:
        outcome = DeliveryOutcome(status="skipped", response_body="subscription inactive or gone")
        _log_attempt(
            client,
            subscription,
            organization_id,
            event_id,
            event_type,
            attempt,
            outcome,
            body,
            None,
        )
        return {"status": outcome.status}

    try:
        secret = decrypt_secret(subscription.encrypted_secret, os.getenv("WEBHOOK_SECRET_KEY", ""))
    except SecretBoxError as exc:
        outcome = DeliveryOutcome(status="dead_letter", response_body=f"secret unavailable: {exc}")
        _log_attempt(
            client,
            subscription,
            organization_id,
            event_id,
            event_type,
            attempt,
            outcome,
            body,
            None,
        )
        return {"status": outcome.status}

    outcome = send_signed(subscription, secret, event_id, event_type, body)
    next_retry_at: datetime | None = None
    if outcome.retryable and attempt < MAX_DELIVERY_ATTEMPTS:
        delay = retry_delay_seconds(attempt)
        next_retry_at = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=delay)
        outcome = DeliveryOutcome(
            status="retrying",
            response_status=outcome.response_status,
            response_body=outcome.response_body,
            duration_ms=outcome.duration_ms,
        )
        current_app.send_task(
            DELIVER_TASK,
            kwargs={
                "organization_id": organization_id,
                "subscription_id": subscription_id,
                "event_id": event_id,
                "event_type": event_type,
                "payload": payload,
                "attempt": attempt + 1,
            },
            countdown=delay,
            ignore_result=True,
        )
    elif outcome.retryable:
        outcome = DeliveryOutcome(
            status="dead_letter",
            response_status=outcome.response_status,
            response_body=outcome.response_body,
            duration_ms=outcome.duration_ms,
        )

    _log_attempt(
        client,
        subscription,
        organization_id,
        event_id,
        event_type,
        attempt,
        outcome,
        body,
        next_retry_at,
    )
    LOGGER.info(
        "webhook_delivery",
        subscription_id=subscription_id,
        event_id=event_id,
        attempt=attempt,
        status=outcome.status,
        response_status=outcome.response_status,
    )
    return {"status": outcome.status, "attempt": attempt}
