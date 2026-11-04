"""Tests for Ozon SKU ad reports collection, parsing, and job state."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

from collectors.ozon.sku_ad_reports import (
    cache_key,
    fetch_report,
    load_active_job,
    parse_report,
    report_is_fresh,
    save_job_state,
)


class _FakeQueryResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def named_results(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeClickHouseJobs:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def insert(self, table: str, data: list[list[Any]], column_names: list[str]) -> None:
        for row in data:
            self.rows.append(dict(zip(column_names, row, strict=True)))

    def query(self, sql: str, parameters: dict[str, Any] | None = None) -> _FakeQueryResult:
        p = parameters or {}
        # Simulate ReplacingMergeTree FINAL by deduplicating on primary key
        latest_by_key: dict[tuple[Any, Any, Any, Any], dict[str, Any]] = {}
        for r in self.rows:
            key = (
                r.get("account_id"),
                r.get("report_kind"),
                r.get("period_key"),
                r.get("job_uuid"),
            )
            latest_by_key[key] = r

        matched = [
            r
            for r in latest_by_key.values()
            if r.get("account_id") == p.get("aid")
            and r.get("report_kind") == p.get("kind")
            and r.get("period_key") == p.get("pkey")
            and r.get("status") not in ("failed", "cancelled")
        ]
        matched.sort(key=lambda r: r.get("updated_at") or datetime.min, reverse=True)
        return _FakeQueryResult(matched[:1])


class SkuAdsTests(unittest.TestCase):
    def test_cached_report_uses_moscow_day(self) -> None:
        today = date(2026, 10, 29)
        self.assertTrue(report_is_fresh(datetime(2026, 10, 28, 21, tzinfo=UTC), today))
        self.assertTrue(report_is_fresh(datetime(2026, 10, 28, 21), today))
        self.assertFalse(report_is_fresh(datetime(2026, 10, 28, 20, 59, tzinfo=UTC), today))

    def test_explicit_sku_and_decimal_comma(self) -> None:
        p = {
            "1": {
                "report": {
                    "rows": [{"sku": "123", "date": "27.10.2026", "moneySpent": "1 234,56"}],
                    "totals": {"moneySpent": "1234,56"},
                }
            }
        }
        result = parse_report(p, ["1"], date(2026, 10, 27), date(2026, 10, 27))
        self.assertEqual(result[(date(2026, 10, 27), "1", "123")], Decimal("1234.56"))

    def test_missing_sku_is_not_allocated(self) -> None:
        p = {
            "1": {
                "report": {"rows": [{"date": "27.10.2026", "moneySpent": "50"}]},
                "totals": {"moneySpent": "50"},
            }
        }
        self.assertEqual(parse_report(p, ["1"], date(2026, 10, 27), date(2026, 10, 27)), {})

    def test_independent_rounding_preserves_sku_rows(self) -> None:
        rows = [{"sku": "123", "date": "27.10.2026", "moneySpent": "0,01"} for _ in range(5)]
        p = {"1": {"report": {"rows": rows, "totals": {"moneySpent": "0,03"}}}}
        r = parse_report(p, ["1"], date(2026, 10, 27), date(2026, 10, 27))
        self.assertEqual(r[(date(2026, 10, 27), "1", "123")], Decimal(".05"))

    def test_corrected_campaign_total_does_not_rescale_sku_spend(self) -> None:
        p = {
            "1": {
                "report": {
                    "rows": [{"sku": "123", "date": "27.10.2026", "moneySpent": "100"}],
                    "totals": {"moneySpent": "80"},
                }
            }
        }
        r = parse_report(p, ["1"], date(2026, 10, 27), date(2026, 10, 27))
        self.assertEqual(r[(date(2026, 10, 27), "1", "123")], Decimal("100"))

    def test_missing_campaign_and_bad_dates_fail(self) -> None:
        with self.assertRaises(ValueError):
            parse_report({}, ["1"], date(2026, 10, 27), date(2026, 10, 27))
        p = {
            "1": {
                "report": {
                    "rows": [{"sku": "123", "date": "26.10.2026", "moneySpent": "1"}],
                    "totals": {"moneySpent": "1"},
                }
            }
        }
        with self.assertRaises(ValueError):
            parse_report(p, ["1"], date(2026, 10, 27), date(2026, 10, 27))

    def test_load_and_save_job_state(self) -> None:
        ch = _FakeClickHouseJobs()
        key = cache_key("acc1", ["101"], date(2026, 10, 1), date(2026, 10, 1))

        # Initially no job
        self.assertIsNone(load_active_job(ch, "acc1", "sku_ads", key))

        # Save pending job
        save_job_state(
            ch,
            account_id="acc1",
            report_kind="sku_ads",
            period_key=key,
            job_uuid="uuid-1",
            status="pending",
        )
        active = load_active_job(ch, "acc1", "sku_ads", key)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active["job_uuid"], "uuid-1")
        self.assertEqual(active["status"], "pending")

        # Mark as failed - load_active_job should ignore it
        save_job_state(
            ch,
            account_id="acc1",
            report_kind="sku_ads",
            period_key=key,
            job_uuid="uuid-1",
            status="failed",
            error="Ozon timeout",
        )
        self.assertIsNone(load_active_job(ch, "acc1", "sku_ads", key))

    def test_fetch_report_handles_failure_and_invalidates_job(self) -> None:
        ch = _FakeClickHouseJobs()
        key = cache_key("acc1", ["101"], date(2026, 10, 1), date(2026, 10, 1))

        mock_client = Mock()
        mock_client._access_token.return_value = "token123"
        mock_client.http.post.return_value = {"UUID": "uuid-failed-1"}
        mock_client._get.return_value = {"state": "FAILED", "error": "Internal Ozon Error"}

        with self.assertRaises(RuntimeError) as ctx:
            fetch_report(
                mock_client,
                ["101"],
                date(2026, 10, 1),
                date(2026, 10, 1),
                ch=ch,
                account_id="acc1",
                period_key=key,
            )

        self.assertIn("Internal Ozon Error", str(ctx.exception))
        # Verify job was recorded as failed in sys_ozon_report_jobs
        self.assertIsNone(load_active_job(ch, "acc1", "sku_ads", key))
        failed_records = [r for r in ch.rows if r["status"] == "failed"]
        self.assertEqual(len(failed_records), 1)
        self.assertEqual(failed_records[0]["job_uuid"], "uuid-failed-1")
        self.assertIn("Internal Ozon Error", failed_records[0]["error"])


if __name__ == "__main__":
    unittest.main()
