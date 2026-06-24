"""Retry helpers and delay policies."""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def wb_retry_delay_seconds(response: httpx.Response) -> float | None:
    """Return WB-specific retry delay from ratelimit headers when possible."""
    retry_after = _parse_float(response.headers.get("X-Ratelimit-Retry"))
    if retry_after is not None and retry_after >= 0:
        return retry_after

    reset_raw = response.headers.get("X-Ratelimit-Reset")
    if not reset_raw:
        return None

    seconds = _parse_float(reset_raw)
    if seconds is not None and seconds >= 0:
        return seconds

    try:
        reset_dt = parsedate_to_datetime(reset_raw)
        if reset_dt.tzinfo is None:
            reset_dt = reset_dt.replace(tzinfo=UTC)
        delta = (reset_dt - datetime.now(UTC)).total_seconds()
        if delta >= 0:
            return float(delta)
    except TypeError, ValueError:
        return None
    return None


def exponential_jitter_delay_seconds(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Backoff delay with jitter for transient failures."""
    safe_attempt = max(1, attempt)
    exponential = min(cap, base * (2 ** (safe_attempt - 1)))
    jitter = random.uniform(0.0, max(0.1, exponential * 0.25))
    return float(min(cap, exponential + jitter))


def sleep_seconds(delay_seconds: float) -> None:
    if delay_seconds <= 0:
        return
    time.sleep(delay_seconds)
