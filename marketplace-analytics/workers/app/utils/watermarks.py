"""Watermark persistence utilities for incremental collectors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import clickhouse_connect
from app.utils.metrics import observe_watermark

DEFAULT_WATERMARK_LAG_HOURS = 48


def _normalize_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def get_watermark(
    client: clickhouse_connect.driver.Client,
    source: str,
    account_id: str,
) -> datetime:
    """Return last known watermark or fallback to now-48h (UTC)."""
    result = client.query(
        """
        SELECT watermark_ts
        FROM sys_watermarks
        WHERE source = %(source)s AND account_id = %(account_id)s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        parameters={"source": source, "account_id": account_id},
    )

    if not result.result_rows:
        fallback = datetime.now(UTC) - timedelta(hours=DEFAULT_WATERMARK_LAG_HOURS)
        observe_watermark(source=source, account_id=account_id, watermark_ts=fallback)
        return fallback

    value = result.result_rows[0][0]
    if not isinstance(value, datetime):
        fallback = datetime.now(UTC) - timedelta(hours=DEFAULT_WATERMARK_LAG_HOURS)
        observe_watermark(source=source, account_id=account_id, watermark_ts=fallback)
        return fallback
    normalized = _normalize_to_utc(value)
    observe_watermark(source=source, account_id=account_id, watermark_ts=normalized)
    return normalized


def set_watermark(
    client: clickhouse_connect.driver.Client,
    source: str,
    account_id: str,
    new_ts: datetime,
) -> bool:
    """Write watermark only if it is greater than the current value."""
    current = get_watermark(client=client, source=source, account_id=account_id)
    candidate = _normalize_to_utc(new_ts)

    if candidate <= current:
        return False

    client.command(
        """
        INSERT INTO sys_watermarks (source, account_id, watermark_ts)
        VALUES (%(source)s, %(account_id)s, %(watermark_ts)s)
        """,
        parameters={
            "source": source,
            "account_id": account_id,
            "watermark_ts": candidate.replace(tzinfo=None),
        },
    )
    observe_watermark(source=source, account_id=account_id, watermark_ts=candidate)
    return True
