"""Webhook event catalogue and HMAC signing shared by the backend and workers.

Signature scheme (documented for receivers in docs/webhooks.md):

    X-BormoStats-Timestamp: <unix seconds>
    X-BormoStats-Signature: v1=<hex HMAC-SHA256(secret, f"{timestamp}.{raw_body}")>
    X-BormoStats-Event-Id:  <uuid>, also sent as Idempotency-Key

Receivers must reject timestamps outside the tolerance window (replay protection)
and de-duplicate by event id.
"""

from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_VERSION = "v1"
DEFAULT_TOLERANCE_SECONDS = 300
MAX_DELIVERY_ATTEMPTS = 6

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "webhook.test",
        "export.completed",
        "insight.created",
        "stock.update.completed",
        "marketplace.action",
    }
)
WILDCARD_EVENT = "*"


def compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def verify_signature(
    secret: str,
    timestamp: int,
    body: bytes,
    signature: str,
    *,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: float | None = None,
) -> bool:
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        return False
    return hmac.compare_digest(compute_signature(secret, timestamp, body), signature)


def retry_delay_seconds(attempt: int) -> int:
    """Exponential backoff: 30s, 60s, 2m, 4m, 8m… capped at one hour."""
    return int(min(3600, 30 * (2 ** max(0, attempt - 1))))


def subscription_matches(events: list[str], event_type: str) -> bool:
    return WILDCARD_EVENT in events or event_type in events
