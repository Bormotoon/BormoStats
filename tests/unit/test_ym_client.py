from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from collectors.ym.client import YmClient
from collectors.ym.errors import YmRateLimitError


class FakeHttp:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = iter(pages)
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        path: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append({"path": path, "headers": headers, "json": json, "params": params})
        return next(self.pages)

    def close(self) -> None:
        pass


def test_cursor_pagination_sends_page_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = YmClient("secret")
    fake = FakeHttp(
        [
            {"result": {"orders": [{"id": 1}], "paging": {"nextPageToken": "next"}}},
            {"result": {"orders": [{"id": 2}], "paging": {}}},
        ]
    )
    monkeypatch.setattr(client, "http", fake)
    assert [row["id"] for row in client._paged("/orders", {}, 10)] == [1, 2]
    assert fake.calls[1]["params"]["pageToken"] == "next"


def test_orders_split_long_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    client = YmClient("secret")
    fake = FakeHttp([{"result": {"orders": []}}] * 3)
    monkeypatch.setattr(client, "http", fake)
    client.orders("1", date(2026, 1, 1), date(2026, 3, 1))
    assert len(fake.calls) == 2
    assert fake.calls[0]["json"]["dates"]["creationDateTo"] == "2026-01-31"
    assert fake.calls[1]["json"]["dates"]["creationDateFrom"] == "2026-01-31"


def test_http_420_is_classified_as_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    client = YmClient("secret")

    def fail(*_: Any, **__: Any) -> None:
        request = httpx.Request("POST", "https://api.partner.market.yandex.ru")
        response = httpx.Response(420, request=request)
        raise httpx.HTTPStatusError("rate limit", request=request, response=response)

    monkeypatch.setattr(client.http, "post", fail)
    with pytest.raises(YmRateLimitError):
        client._post("/orders", {})


def test_report_download_selects_detail_sheet_without_double_counting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import zipfile

    import httpx

    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("summary.csv", "AMOUNT\n999\n")
        archive.writestr(
            "transaction_date.csv", "TRANSACTION_DATE;TRANSACTION_SUM\n2026-11-02;10\n"
        )
    response = httpx.Response(
        200, content=content.getvalue(), request=httpx.Request("GET", "https://example.org/report")
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: response)
    with YmClient("secret") as client:
        rows = client._download_report(
            "https://example.org/report", "CSV", report_type="united-netting"
        )
    assert rows == [{"TRANSACTION_DATE": "2026-11-02", "TRANSACTION_SUM": "10"}]


def test_campaigns_iterate_all_pages_and_feedback_limit_is_50(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = YmClient("secret")

    class Fake:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def get(self, path: str, *, headers: Any, params: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(params)
            return {
                "campaigns": [{"id": len(self.calls)}],
                "paging": {"nextPageToken": "next" if len(self.calls) == 1 else ""},
            }

        def close(self) -> None:
            pass

    fake = Fake()
    monkeypatch.setattr(client, "http", fake)
    assert [r["id"] for r in client.campaigns()] == [1, 2]
    assert fake.calls[1]["pageToken"] == "next"
    calls: list[int] = []
    monkeypatch.setattr(
        client, "_paged", lambda path, body, page_size: calls.append(page_size) or []
    )
    client.feedbacks("1", {}, page_size=200)
    assert calls == [50]
