from __future__ import annotations

from datetime import date
from typing import Any

from collectors.wb import endpoints
from collectors.wb.client import WbApiClient


class _FakeAnalytics:
    def __init__(self, pages: dict[tuple[str, int], list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def post(self, path: str, headers: dict[str, str], json: dict[str, Any]) -> Any:
        assert path == endpoints.FUNNEL_PATH
        self.calls.append(json)
        period = json["selectedPeriod"]
        assert period["start"] == period["end"]
        products = self.pages.get((period["start"], json["offset"]), [])
        return {"data": {"products": products, "currency": "RUB"}}

    def close(self) -> None:
        pass


def test_funnel_daily_requests_each_day_and_paginates(monkeypatch: Any) -> None:
    monkeypatch.setattr(endpoints, "FUNNEL_PAGE_LIMIT", 2)
    fake = _FakeAnalytics(
        {
            ("2026-09-27", 0): [{"product": {"nmId": 1}}, {"product": {"nmId": 2}}],
            ("2026-09-27", 2): [{"product": {"nmId": 3}}],
            ("2026-09-28", 0): [{"product": {"nmId": 1}}],
        }
    )
    client = WbApiClient(statistics_token="s", analytics_token="a")
    client.analytics.close()
    client.analytics = fake  # type: ignore[assignment]

    records = client.funnel_daily(date(2026, 9, 27), date(2026, 9, 28))

    assert [r["product"]["nmId"] for r in records] == [1, 2, 3, 1]
    assert all(r["currency"] == "RUB" for r in records)
    assert [(c["selectedPeriod"]["start"], c["offset"]) for c in fake.calls] == [
        ("2026-09-27", 0),
        ("2026-09-27", 2),
        ("2026-09-28", 0),
    ]


class _FakeStocksAnalytics:
    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[dict[str, Any]] = []

    def post(self, path: str, headers: dict[str, str], json: dict[str, Any]) -> Any:
        assert path == endpoints.STOCKS_PATH
        assert headers == {"Authorization": "a"}
        self.calls.append(json)
        end = min(json["offset"] + json["limit"], self.total)
        items = [{"chrtId": i} for i in range(json["offset"], end)]
        return {"data": {"items": items}}

    def close(self) -> None:
        pass


def test_stocks_use_analytics_report_and_paginate(monkeypatch: Any) -> None:
    monkeypatch.setattr(endpoints, "STOCKS_PAGE_LIMIT", 2)
    fake = _FakeStocksAnalytics(total=3)
    client = WbApiClient(statistics_token="s", analytics_token="a")
    client.analytics.close()
    client.analytics = fake  # type: ignore[assignment]

    records = client.stocks()

    assert [r["chrtId"] for r in records] == [0, 1, 2]
    assert [c["offset"] for c in fake.calls] == [0, 2]
