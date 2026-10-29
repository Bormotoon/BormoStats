from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.beat_schedule import beat_schedule
from app.tasks import marts, ozon_collect, reports
from app.utils import data_quality, watermarks
from app.utils.locking import LockNotAcquiredError

from tests.fakes import FakeClickHouse


class Checkpoints:
    def __init__(self):
        self.values = {}

    def hget(self, key, field):
        return self.values.get((key, field))

    def hset(self, key, field, value):
        self.values[key, field] = value

    def expire(self, *args):
        return True


@pytest.fixture
def daily(monkeypatch):
    cache = Checkpoints()
    calls = []

    @contextmanager
    def scope(**kwargs):
        yield SimpleNamespace(ensure_held=lambda: None)

    monkeypatch.setattr(reports, "lock_scope", scope)
    monkeypatch.setattr(reports, "get_redis_client", lambda: cache)
    monkeypatch.setattr(reports, "get_ch_client", object)
    monkeypatch.setattr(reports, "log_task_run", lambda *a, **kw: None)
    monkeypatch.setattr(
        reports,
        "REPORT_STEPS",
        (
            ("tasks.ozon_collect.finance", ()),
            ("tasks.transforms.transform", (90,)),
            ("tasks.marts.marts", (90,)),
        ),
    )

    def call(name, args):
        calls.append(name)
        return {"status": "success"}

    monkeypatch.setattr(reports, "_call_step", call)
    return cache, calls


def test_completed_day_does_not_fetch_again(daily):
    _, calls = daily
    assert reports._run_daily("2026-10-29")["status"] == "success"
    assert len(calls) == 3
    assert reports._run_daily("2026-10-29")["reason"] == "already_completed"
    assert len(calls) == 3
    assert reports._run_daily("2026-10-30")["status"] == "success"
    assert len(calls) == 6


def test_retry_resumes_without_refetching_completed_sources(daily, monkeypatch):
    cache, calls = daily
    original = reports._call_step

    def failing(name, args):
        if "transforms" in name:
            raise RuntimeError("database unavailable")
        return original(name, args)

    monkeypatch.setattr(reports, "_call_step", failing)
    with pytest.raises(RuntimeError, match="database unavailable"):
        reports._run_daily("2026-10-29")
    assert calls == ["tasks.ozon_collect.finance"]
    assert cache.hget("reports:daily:v1:2026-10-29", "completed") is None
    monkeypatch.setattr(reports, "_call_step", original)
    reports._run_daily("2026-10-29")
    assert calls == [
        "tasks.ozon_collect.finance",
        "tasks.transforms.transform",
        "tasks.marts.marts",
    ]


@pytest.mark.parametrize(
    "result",
    [
        {"status": "skipped", "reason": "lock_not_acquired"},
        {"status": "failed"},
    ],
)
def test_incomplete_source_blocks_rebuild_and_is_not_checkpointed(daily, monkeypatch, result):
    cache, calls = daily
    monkeypatch.setattr(reports, "_call_step", lambda *a: result)
    with pytest.raises((RuntimeError, LockNotAcquiredError)):
        reports._run_daily("2026-10-29")
    assert not cache.values
    assert not calls


def test_missing_optional_credentials_are_visible_in_result(daily, monkeypatch):
    original = reports._call_step
    monkeypatch.setattr(
        reports,
        "_call_step",
        lambda n, a: (
            {"status": "skipped", "reason": "missing Ozon credentials"}
            if "ozon_collect" in n
            else original(n, a)
        ),
    )
    result = reports._run_daily("2026-10-29")
    assert result["steps"]["tasks.ozon_collect.finance"]["status"] == "skipped"


def test_schedule_has_no_independent_collectors_or_rebuilds():
    entry = beat_schedule["daily_reports"]
    assert entry["schedule"].hour == {6}
    assert entry["schedule"].minute == {0}
    assert reports.REPORT_TIMEZONE == "Europe/Moscow"
    assert not [
        e
        for e in beat_schedule.values()
        if e["task"].startswith(
            (
                "tasks.wb_collect.",
                "tasks.ozon_collect.",
                "tasks.transforms.",
                "tasks.marts.",
            )
        )
    ]
    names = [name for name, args in reports.REPORT_STEPS]
    assert len(names) == len(set(names))
    assert names.index("tasks.ozon_collect.ozon_finance_incremental") < names.index(
        "tasks.ozon_collect.ozon_ads_sku_backfill_days"
    )
    assert (
        names.index("tasks.transforms.transform_backfill_days")
        < names.index("tasks.marts.build_marts_backfill_days")
        < names.index("tasks.insights.generate_actionable_tasks")
    )


def test_postings_refresh_old_statuses_without_second_fetch(monkeypatch):
    from contextlib import nullcontext

    ch = FakeClickHouse()
    ozon = Mock()
    ozon.postings_since.return_value = []
    monkeypatch.setattr(ozon_collect, "_ozon_client", lambda: ozon)
    monkeypatch.setattr(ozon_collect, "get_ch_client", lambda: ch)
    monkeypatch.setattr(ozon_collect, "get_redis_client", object)
    monkeypatch.setattr(ozon_collect, "lock_scope", lambda **_: nullcontext())
    monkeypatch.setattr(ozon_collect, "get_watermark", lambda *a: datetime.now(UTC))
    monkeypatch.setattr(ozon_collect, "set_watermark", lambda *a: None)
    monkeypatch.setattr(ozon_collect, "log_task_run", lambda *a: None)
    ozon_collect._collect_postings("default")
    kwargs = ozon.postings_since.call_args.kwargs
    assert (kwargs["to_ts"] - kwargs["from_ts"]).days == 90
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


@pytest.mark.parametrize("age_hours,stale", [(25, False), (31, True)])
def test_daily_freshness_allows_normal_interval_but_detects_missed_cycle(age_hours, stale):
    class Database:
        def query(self, sql, **kwargs):
            value = (
                datetime.now(UTC) - timedelta(hours=age_hours) if "max(updated_at)" in sql else 1
            )
            return SimpleNamespace(result_rows=[(value,)])

    issue = data_quality._check_stale_marts(Database())
    assert (issue is not None) is stale
