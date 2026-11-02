"""Yandex collection contracts without access to seller credentials."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
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
