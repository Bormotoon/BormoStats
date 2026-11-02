from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.tasks import marts, ozon_collect
from app.utils import data_quality, watermarks

from tests.fakes import FakeClickHouse


def test_postings_resume_from_watermark(monkeypatch):
    from contextlib import nullcontext

    ch = FakeClickHouse()
    ozon = Mock()
    ozon.postings_since.return_value = []
    monkeypatch.setattr(ozon_collect, "_ozon_client", lambda: ozon)
    monkeypatch.setattr(ozon_collect, "get_ch_client", lambda: ch)
    monkeypatch.setattr(ozon_collect, "get_redis_client", object)
    monkeypatch.setattr(ozon_collect, "lock_scope", lambda **_: nullcontext())
    watermark = datetime.now(UTC) - timedelta(minutes=20)
    monkeypatch.setattr(ozon_collect, "get_watermark", lambda *a: watermark)
    monkeypatch.setattr(ozon_collect, "set_watermark", lambda *a: None)
    monkeypatch.setattr(ozon_collect, "log_task_run", lambda *a: None)
    ozon_collect._collect_postings("default")
    kwargs = ozon.postings_since.call_args.kwargs
    assert kwargs["from_ts"] == watermark
    ozon.postings_since.assert_called_once()


def test_watermark_insert_preserves_timezone(monkeypatch):
    ch = Mock()
    monkeypatch.setattr(
        watermarks, "get_watermark", lambda **kw: datetime(2026, 10, 28, tzinfo=UTC)
    )
    candidate = datetime(2026, 10, 29, tzinfo=UTC)
    assert watermarks.set_watermark(ch, "sales", "default", candidate)
    assert ch.command.call_args.kwargs["parameters"]["watermark_ts"] == candidate
    assert ch.command.call_args.kwargs["parameters"]["watermark_ts"].tzinfo is not None


def test_rebuild_cleans_full_ad_window_and_preserves_supply_history(monkeypatch):
    from contextlib import nullcontext

    ch = Mock()
    monkeypatch.setattr(marts, "get_ch_client", lambda: ch)
    monkeypatch.setattr(marts, "get_redis_client", object)
    monkeypatch.setattr(marts, "rebuild_task_scope", lambda **kw: nullcontext())
    monkeypatch.setattr(marts, "log_task_run", lambda *a: None)
    monkeypatch.setattr(marts, "bump_generation", lambda *a: None)
    marts.build_marts_recent()
    deletes = [c for c in ch.command.call_args_list if c.args[0].startswith("ALTER TABLE")]
    ad_delete = next(c for c in deletes if "mrt_ad_performance_daily" in c.args[0])
    assert ad_delete.kwargs["parameters"]["days"] == 60
    supply_delete = next(c for c in deletes if "mrt_supply_planning_daily" in c.args[0])
    assert "WHERE day = " in supply_delete.args[0]


@pytest.mark.parametrize("age_hours,stale", [(1, False), (3, True)])
def test_intraday_freshness_detects_stale_marts(age_hours, stale):
    class Database:
        def query(self, sql, **kwargs):
            value = (
                datetime.now(UTC) - timedelta(hours=age_hours) if "max(updated_at)" in sql else 1
            )
            return SimpleNamespace(result_rows=[(value,)])

    issue = data_quality._check_stale_marts(Database())
    assert (issue is not None) is stale


def test_original_collectors_and_additional_sources_have_independent_timers():
    from app.beat_schedule import beat_schedule

    assert "daily_reports" not in beat_schedule
    assert all(e["task"] != "tasks.reports.collect_daily" for e in beat_schedule.values())
    for name in ("ozon_buyouts_week", "ozon_realization", "ozon_ads_sku"):
        entry = beat_schedule[name]
        function_name = entry["task"].rsplit(".", 1)[1]
        assert getattr(ozon_collect, function_name).name == entry["task"]
    assert beat_schedule["ozon_postings_incremental"]["schedule"].minute == {0, 20, 40}
    assert beat_schedule["wb_sales_incremental"]["schedule"].minute == {0, 15, 30, 45}
    assert beat_schedule["history_ozon_catalog"]["schedule"].hour == set(range(24))


def test_finance_balance_uses_original_recent_window(monkeypatch):
    today = datetime(2026, 11, 2, tzinfo=UTC).date()
    collect = Mock(return_value={"status": "success"})
    monkeypatch.setattr(ozon_collect, "_ozon_today", lambda: today)
    monkeypatch.setattr(ozon_collect, "_collect_finance_balance", collect)
    assert ozon_collect.ozon_finance_balance("account-1")["status"] == "success"
    collect.assert_called_once_with(
        account_id="account-1",
        from_day=today - timedelta(days=ozon_collect.FINANCE_BALANCE_LOOKBACK_DAYS),
    )
