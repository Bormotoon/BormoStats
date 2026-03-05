"""Date/time chunking helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Iterator


def date_chunks(start: date, end: date, chunk_days: int) -> Iterator[tuple[date, date]]:
    """Yield [start, end] date windows with fixed chunk length in days."""
    safe_chunk = max(1, chunk_days)
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=safe_chunk - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def datetime_chunks(
    start: datetime,
    end: datetime,
    chunk_hours: int,
) -> Iterator[tuple[datetime, datetime]]:
    """Yield [start, end] datetime windows with fixed chunk size in hours."""
    safe_chunk = max(1, chunk_hours)
    current = start.astimezone(UTC)
    target = end.astimezone(UTC)
    while current <= target:
        chunk_end = min(current + timedelta(hours=safe_chunk), target)
        yield current, chunk_end
        current = chunk_end
