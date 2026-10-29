from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from app.tasks import ozon_collect as collector

from collectors.ozon.sku_ad_reports import cache_key


class ReportsDb:
    def __init__(self):
        self.jobs = {}
        self.rows = []

    def query(self, sql, parameters=None):
        p = parameters or {}
        if "SELECT report_uuid" in sql:
            rows = [self.jobs[p["key"]]] if p["key"] in self.jobs else []
        elif "SELECT DISTINCT campaign_id" in sql:
            rows = [("1",)]
        elif "SELECT day,campaign_id,sku" in sql:
            rows = [(p["start"], "1", "999")]
        else:
            raise AssertionError(sql)
        return SimpleNamespace(result_rows=rows)

    def insert(self, table, rows, column_names):
        if table == "raw_ozon_sku_report_jobs":
            for row in rows:
                record = dict(zip(column_names, row, strict=True))
                self.jobs[record["cache_key"]] = (
                    record["report_uuid"],
                    record["payload"],
                    record["updated_at"],
                )
        elif table == "raw_ozon_ads_sku_daily":
            self.rows.extend(dict(zip(column_names, row, strict=True)) for row in rows)
        else:
            raise AssertionError(table)


def test_stable_daily_reports_reuse_fresh_jobs_and_clear_removed_skus(monkeypatch):
    db = ReportsDb()
    today = datetime.now(collector.OZON_TZ).date()
    from datetime import timedelta

    yesterday = today - timedelta(days=1)
    old_day = today - timedelta(days=2)
    payload = {"1": {"report": {"rows": []}}}
    db.jobs[cache_key("default", ["1"], yesterday, yesterday)] = (
        "fresh",
        json.dumps(payload),
        datetime.now(UTC),
    )
    db.jobs[cache_key("default", ["1"], old_day, old_day)] = (
        "stale",
        json.dumps(payload),
        datetime(2000, 1, 1, tzinfo=UTC),
    )
    perf = Mock()
    monkeypatch.setattr(collector, "_ozon_performance_client", lambda: perf)
    monkeypatch.setattr(collector, "get_ch_client", lambda: db)
    monkeypatch.setattr(collector, "get_redis_client", object)
    monkeypatch.setattr(collector, "lock_scope", lambda **_: nullcontext())
    monkeypatch.setattr(collector, "log_task_run", lambda *a, **kw: None)
    fetch = Mock(return_value=({}, "new", payload))
    monkeypatch.setattr(collector, "fetch_report", fetch)
    assert collector.ozon_ads_sku_backfill_days(2)["status"] == "success"
    fetch.assert_called_once()
    args, kwargs = fetch.call_args
    assert args[2:] == (old_day, old_day)
    assert kwargs["job_uuid"] is None
    assert len(db.rows) == 2
    assert all(r["sku"] == "999" and r["cost"] == 0 for r in db.rows)
    assert collector.ozon_ads_sku_backfill_days(2)["status"] == "success"
    fetch.assert_called_once()


def test_call_step_imports_registered_task(monkeypatch):
    from app.tasks import reports

    task = Mock(return_value={"status": "success"})
    monkeypatch.setattr(collector, "ozon_buyouts_week", task)
    assert reports._call_step("tasks.ozon_collect.ozon_buyouts_week", (7,))["status"] == "success"
    task.assert_called_once_with(7)
