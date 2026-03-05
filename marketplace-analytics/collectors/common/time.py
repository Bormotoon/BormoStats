"""Time helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from dateutil import parser


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = parser.isoparse(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def as_ch_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
