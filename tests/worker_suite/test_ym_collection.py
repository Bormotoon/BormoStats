"""Yandex collection contracts without access to seller credentials."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from app.tasks import reviews as review_tasks
from app.tasks import ym_collect


@pytest.mark.parametrize("report_type", ["shows-sales", "shows-boost", "united-netting"])
def test_report_windows_and_required_body(
    monkeypatch: pytest.MonkeyPatch, report_type: str
) -> None:
    calls: list[dict[str, Any]] = []

    class Client:
        def campaigns(self) -> list[dict[str, Any]]:
            return [{"id": 222, "business": {"id": 111}}]

        def generate_and_fetch_report(self, kind: str, body: dict[str, Any]) -> list[Any]:
            assert kind == report_type
            calls.append(body)
            return []

    def collect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        args[4](Client(), datetime(2026, 11, 2, tzinfo=UTC))
        return {"status": "success"}

    monkeypatch.setattr(ym_collect, "YM_BUSINESS_ID", "111")
    monkeypatch.setattr(ym_collect, "YM_CAMPAIGN_ID", "222")
    monkeypatch.setattr(ym_collect, "get_ch_client", lambda: object())
    monkeypatch.setattr(
        ym_collect,
        "get_watermark",
        lambda *_args: datetime(2026, 8, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(ym_collect, "_collect", collect)
    ym_collect._collect_report(
        "ym_finance_backfill_days", report_type, 100, "raw_ym_finance", [], lambda x: x
    )
    assert len(calls) == 4
    for body in calls:
        assert ("businessId" in body) != ("campaignId" in body)
        if report_type == "shows-sales":
            assert body["grouping"] == "OFFERS"
        if report_type == "shows-boost":
            assert body["attributionType"] == "CLICKS"


def test_product_resolution_recurses_into_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        def offer_mappings(self, business_id: str) -> list[dict[str, Any]]:
            return [{"offer": {"offerId": "article"}, "mapping": {"marketSku": 123}}]

    rows = ym_collect._with_product_ids(Client(), [{"items": [{"offerId": "article"}]}])  # type: ignore[arg-type]
    assert rows[0]["items"][0]["marketSku"] == 123


def test_catalog_task_wires_fetch_and_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    def collect(
        name: str, source: str, table: str, columns: Any, fetch: Any, parse: Any
    ) -> dict[str, Any]:
        assert name == "ym_offer_mappings_snapshot"
        assert parse is ym_collect.parse_offer_mappings
        assert callable(fetch)
        return {"status": "success"}

    monkeypatch.setattr(ym_collect, "_collect", collect)
    assert ym_collect.ym_offer_mappings_snapshot()["status"] == "success"


def test_business_wide_ads_are_not_assigned_to_one_of_multiple_shops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def campaigns(self) -> list[dict[str, Any]]:
            return [{"id": 222, "business": {"id": 111}}, {"id": 333, "business": {"id": 111}}]

    def collect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        args[4](Client(), datetime(2026, 11, 2, tzinfo=UTC))
        return {}

    monkeypatch.setattr(ym_collect, "YM_BUSINESS_ID", "111")
    monkeypatch.setattr(ym_collect, "YM_CAMPAIGN_ID", "222")
    monkeypatch.setattr(ym_collect, "_collect", collect)
    with pytest.raises(ValueError, match="business-wide"):
        ym_collect._collect_report("ym_ads_recent", "shows-boost", 3, "raw_ym_ads", [], lambda x: x)


def test_tariff_snapshot_builds_only_complete_offers(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, Any]] = []

    class Client:
        def offer_mappings(self, business_id: str) -> list[dict[str, Any]]:
            return [
                {
                    "offer": {
                        "offerId": "a",
                        "marketCategoryId": 5,
                        "weightDimensions": {"length": 10, "width": 20, "height": 30, "weight": 1},
                    }
                },
                {"offer": {"offerId": "incomplete"}},
            ]

        def offer_prices(self, campaign_id: str) -> list[dict[str, Any]]:
            return [{"offerId": "a", "price": {"value": 1000}}]

        def calculate_tariffs(
            self, campaign_id: str, offers: list[dict[str, Any]]
        ) -> list[dict[str, Any]]:
            requests.extend(offers)
            return [{"tariffs": [{"type": "FEE", "amount": 80}]}]

    def collect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        rows = args[4](Client(), datetime.now(UTC))
        assert rows[0]["_offerId"] == "a"
        assert args[5](rows, run_id="r", account_id="a")[0]["fee"] == 80
        return {"status": "success"}

    monkeypatch.setattr(ym_collect, "_collect", collect)
    assert ym_collect.ym_tariff_quotes_snapshot()["status"] == "success"
    assert requests[0]["categoryId"] == 5 and requests[0]["price"] == 1000


def test_stats_backfill_splits_dates_and_does_not_advance_recent_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows: list[tuple[datetime, datetime]] = []

    class Client:
        def stats_orders(self, campaign_id: str, start: datetime, end: datetime) -> list[Any]:
            windows.append((start, end))
            return []

    def collect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["watermark"] is False
        args[4](Client(), datetime(2026, 11, 2, tzinfo=UTC))
        return {"status": "success", "rows": 0}

    monkeypatch.setattr(ym_collect, "_collect", collect)
    assert ym_collect.ym_order_stats_backfill_days(60)["status"] == "success"
    assert len(windows) == 3
    assert all((end - start).days <= 29 for start, end in windows)


@pytest.mark.parametrize("outage_days", [7, 30])
def test_recent_finance_recovers_from_initial_depth_after_outage(
    monkeypatch: pytest.MonkeyPatch, outage_days: int
) -> None:
    from datetime import timedelta

    now = datetime(2026, 11, 2, tzinfo=UTC)
    oldest = now - timedelta(days=outage_days)
    observed: list[tuple[str, str, int]] = []

    class Client:
        def campaigns(self) -> list[dict[str, Any]]:
            return [{"id": 222, "business": {"id": 111}}]

        def generate_and_fetch_report(self, report_type: str, body: dict[str, Any]) -> list[Any]:
            observed.append((report_type, body["dateFrom"], outage_days))
            return []

    monkeypatch.setattr(ym_collect, "YM_BUSINESS_ID", "111")
    monkeypatch.setattr(ym_collect, "YM_CAMPAIGN_ID", "222")
    monkeypatch.setattr(ym_collect, "YM_ACCOUNT_ID", "acct")
    monkeypatch.setattr(ym_collect, "get_ch_client", lambda: object())
    monkeypatch.setattr(
        ym_collect,
        "get_watermark",
        lambda *_args, **kwargs: now - timedelta(days=kwargs["initial_days"]),
    )
    monkeypatch.setattr(ym_collect, "normalize_report_row", lambda row: row)
    monkeypatch.setattr(ym_collect, "_with_product_ids", lambda _c, rows: rows)
    monkeypatch.setattr(ym_collect, "_client", lambda: Client())
    monkeypatch.setattr(ym_collect, "insert_rows", lambda *_: 0)
    monkeypatch.setattr(ym_collect, "lock_scope", lambda *_a, **_k: object())

    class Lock:
        def __enter__(self) -> Lock:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def ensure_held(self) -> None:
            return None

    monkeypatch.setattr(ym_collect, "lock_scope", lambda *_a, **_k: Lock())
    monkeypatch.setattr(ym_collect, "get_redis_client", lambda: object())
    monkeypatch.setattr(ym_collect, "new_run_context", lambda: ("run", now))
    monkeypatch.setattr(ym_collect, "log_task_run", lambda *a, **k: None)
    monkeypatch.setattr(ym_collect, "set_watermark", lambda *a: None)
    monkeypatch.setattr(ym_collect, "_client", lambda: Client())
    monkeypatch.setattr(ym_collect, "_collect", lambda *a, **k: a[4](Client(), now))
    ym_collect._collect_report(
        "ym_finance_recent",
        "united-netting",
        outage_days,
        "raw_ym_finance",
        [],
        lambda *_a, **_k: [],
    )
    assert observed[0][1] <= oldest.date().isoformat()


def test_recent_report_reads_dataset_watermark_and_backfill_uses_requested_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date, timedelta

    watermarks: list[tuple[str, str]] = []
    bodies: list[dict[str, Any]] = []

    class Client:
        def campaigns(self) -> list[dict[str, Any]]:
            return [{"id": 222, "business": {"id": 111}}]

        def generate_and_fetch_report(self, kind: str, body: dict[str, Any]) -> list[Any]:
            bodies.append(body)
            return []

    def get_watermark(_ch: Any, source: str, account: str, *, initial_days: int = 2) -> datetime:
        watermarks.append((source, account))
        return datetime(2026, 10, 1, tzinfo=UTC)

    def collect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        args[4](Client(), datetime(2026, 11, 2, tzinfo=UTC))
        return {"status": "success"}

    monkeypatch.setattr(ym_collect, "YM_BUSINESS_ID", "111")
    monkeypatch.setattr(ym_collect, "YM_CAMPAIGN_ID", "222")
    monkeypatch.setattr(ym_collect, "get_ch_client", lambda: object())
    monkeypatch.setattr(ym_collect, "get_watermark", get_watermark)
    monkeypatch.setattr(ym_collect, "_collect", collect)
    ym_collect._collect_report("ym_ads_recent", "shows-boost", 3, "raw_ym_ads", [], lambda x: x)
    assert watermarks == [("ym_ads", ym_collect.YM_ACCOUNT_ID)]
    assert bodies[0]["dateFrom"] == (date(2026, 10, 1) - timedelta(days=2)).isoformat()
    bodies.clear()
    watermarks.clear()
    monkeypatch.setattr(
        ym_collect,
        "get_watermark",
        lambda *_args: pytest.fail("backfill must not read recent watermark"),
    )
    ym_collect._collect_report(
        "ym_finance_backfill_days", "united-netting", 30, "raw_ym_finance", [], lambda x: x
    )
    assert bodies[0]["dateFrom"] == "2026-10-03"
    assert watermarks == []


def test_report_backfill_does_not_persist_recent_watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[tuple[str, str, datetime]] = []

    class FakeClient:
        def close(self) -> None:
            pass

    class FakeLock:
        def __enter__(self) -> FakeLock:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def ensure_held(self) -> None:
            pass

    monkeypatch.setattr(ym_collect, "_client", lambda: FakeClient())
    monkeypatch.setattr(ym_collect, "get_ch_client", lambda: object())
    monkeypatch.setattr(ym_collect, "get_redis_client", lambda: object())
    monkeypatch.setattr(ym_collect, "lock_scope", lambda *_args, **_kwargs: FakeLock())
    monkeypatch.setattr(ym_collect, "insert_rows", lambda *_: 0)
    monkeypatch.setattr(ym_collect, "set_watermark", lambda *args: saved.append(args[1:]))
    monkeypatch.setattr(ym_collect, "log_task_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(ym_collect, "new_run_context", lambda: ("run", datetime.now(UTC)))
    monkeypatch.setattr(ym_collect, "normalize_report_row", lambda row: row)
    monkeypatch.setattr(ym_collect, "_with_product_ids", lambda _client, rows: rows)
    monkeypatch.setattr(ym_collect, "YM_BUSINESS_ID", "111")
    monkeypatch.setattr(ym_collect, "YM_CAMPAIGN_ID", "222")
    monkeypatch.setattr(ym_collect, "parse_shows_sales", lambda *args, **kwargs: [])

    class ReportClient:
        def generate_and_fetch_report(self, *_: Any, **__: Any) -> list[Any]:
            return []

        def campaigns(self) -> list[dict[str, Any]]:
            return [{"id": 222, "business": {"id": 111}}]

        def close(self) -> None:
            pass

    monkeypatch.setattr(ym_collect, "_client", lambda: ReportClient())
    ym_collect._collect_report(
        "ym_funnel_backfill_days", "shows-sales", 7, "raw_ym_funnel", [], lambda *_a, **_k: []
    )
    assert saved == []


def test_ym_backfill_pipeline_runs_all_stages_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        ym_collect,
        "ym_funnel_backfill_days",
        lambda days: calls.append(("collect", days)) or {"status": "success", "rows": 1},
    )
    monkeypatch.setattr(
        "app.tasks.transforms._run_transform",
        lambda days, task: calls.append(("transform", days)) or {"status": "success", "days": days},
    )
    monkeypatch.setattr(
        "app.tasks.marts._run_marts",
        lambda days, task: calls.append(("marts", days)) or {"status": "success", "days": days},
    )
    result = ym_collect.ym_backfill_pipeline("funnel", 30)
    assert result["status"] == "success"
    assert calls == [("collect", 30), ("transform", 30), ("marts", 30)]


def test_ym_backfill_pipeline_stops_on_collection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ym_collect, "ym_finance_backfill_days", lambda _: {"status": "failed"})
    result = ym_collect.ym_backfill_pipeline("finance", 7)
    assert result == {"status": "failed", "stage": "collect", "collection": {"status": "failed"}}


def test_auto_review_replies_are_blocked_before_marketplace_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections import Counter

    monkeypatch.setattr(review_tasks, "_auto_reply_actions_enabled", lambda: False)
    monkeypatch.setattr(
        review_tasks, "load_settings", lambda *_: pytest.fail("must not read settings")
    )
    assert review_tasks.auto_reply(object(), "org", 10, Counter()) == 0


def test_fill_ym_names_enriches_offer_and_title_from_dim_product() -> None:
    class FakeResult:
        def __init__(self) -> None:
            self.result_rows = [("555", "OFFER-555", "Название из каталога")]

    class FakeCh:
        def query(self, _sql: str, parameters: dict[str, Any]) -> FakeResult:
            assert parameters["aid"] == "acct"
            return FakeResult()

    rows = [
        {"product_id": "555", "offer_id": "", "product_name": ""},
        {"product_id": "OFFER-555", "offer_id": "OFFER-555", "product_name": ""},
    ]
    review_tasks._fill_ym_names(FakeCh(), "acct", rows)
    assert rows[0] == {
        "product_id": "555",
        "offer_id": "OFFER-555",
        "product_name": "Название из каталога",
    }
    assert rows[1] == {
        "product_id": "555",
        "offer_id": "OFFER-555",
        "product_name": "Название из каталога",
    }


def test_two_shops_of_same_business_keep_isolated_watermarks_and_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watermarks: dict[tuple[str, str], datetime] = {}
    locks_seen: list[tuple[str, str]] = []

    class FakeLock:
        def __enter__(self) -> FakeLock:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def ensure_held(self) -> None:
            pass

    def record_lock(_redis: Any, *, source: str, account_id: str, **_kwargs: Any) -> FakeLock:
        locks_seen.append((source, account_id))
        return FakeLock()

    class ReportClient:
        def generate_and_fetch_report(self, *_: Any, **__: Any) -> list[Any]:
            return []

        def campaigns(self) -> list[dict[str, Any]]:
            return [{"id": 222, "business": {"id": 111}}, {"id": 333, "business": {"id": 111}}]

        def close(self) -> None:
            pass

    monkeypatch.setattr(ym_collect, "_client", lambda: ReportClient())
    monkeypatch.setattr(ym_collect, "get_ch_client", lambda: object())
    monkeypatch.setattr(ym_collect, "get_redis_client", lambda: object())
    monkeypatch.setattr(ym_collect, "lock_scope", record_lock)
    monkeypatch.setattr(ym_collect, "insert_rows", lambda *_: 0)
    monkeypatch.setattr(ym_collect, "log_task_run", lambda *_a, **_kw: None)
    monkeypatch.setattr(ym_collect, "new_run_context", lambda: ("run", datetime.now(UTC)))
    monkeypatch.setattr(ym_collect, "normalize_report_row", lambda row: row)
    monkeypatch.setattr(ym_collect, "_with_product_ids", lambda _client, rows: rows)
    monkeypatch.setattr(ym_collect, "YM_BUSINESS_ID", "111")
    monkeypatch.setattr(
        ym_collect,
        "get_watermark",
        lambda _ch, source, account_id, **_kw: watermarks.get(
            (source, account_id), datetime(2026, 10, 29, tzinfo=UTC)
        ),
    )
    monkeypatch.setattr(
        ym_collect,
        "set_watermark",
        lambda _ch, source, account_id, ts: (
            watermarks.__setitem__((source, account_id), ts) or True
        ),
    )

    for shop_account, campaign_id in (("shop-101", "222"), ("shop-102", "333")):
        monkeypatch.setattr(ym_collect, "YM_ACCOUNT_ID", shop_account)
        monkeypatch.setattr(ym_collect, "YM_CAMPAIGN_ID", campaign_id)
        res = ym_collect._collect_report(
            "ym_finance_recent",
            "united-netting",
            2,
            "raw_ym_finance",
            [],
            lambda *_a, **_k: [],
        )
        assert res["status"] == "success"

    assert ("ym_finance", "shop-101") in locks_seen
    assert ("ym_finance", "shop-102") in locks_seen
    assert ("ym_finance", "shop-101") in watermarks
    assert ("ym_finance", "shop-102") in watermarks
