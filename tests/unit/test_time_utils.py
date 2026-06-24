from __future__ import annotations

from datetime import UTC, datetime

from collectors.common.time import as_ch_datetime, parse_dt


def test_parse_dt_assumes_utc_for_naive_values() -> None:
    parsed = parse_dt("2026-03-01T12:00:00")
    assert parsed is not None
    assert parsed.tzinfo == UTC
    assert parsed.isoformat() == "2026-03-01T12:00:00+00:00"


def test_parse_dt_converts_offset_values_to_utc() -> None:
    parsed = parse_dt("2026-03-01T15:00:00+03:00")
    assert parsed is not None
    assert parsed.tzinfo == UTC
    assert parsed.isoformat() == "2026-03-01T12:00:00+00:00"


def test_as_ch_datetime_strips_timezone_for_clickhouse() -> None:
    value = datetime(2026, 3, 1, 15, 0, 0, tzinfo=UTC)
    converted = as_ch_datetime(value)
    assert converted.tzinfo is None
    assert converted.isoformat() == "2026-03-01T15:00:00"
