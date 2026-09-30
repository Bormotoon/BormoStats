from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from collectors.ozon import endpoints
from collectors.ozon.client import OzonApiClient, OzonPerformanceClient
from collectors.ozon.errors import is_capability_error

Handler = Callable[[str, dict[str, Any] | None, dict[str, Any] | None], Any]


class _FakeHttp:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

    def post(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(("POST", path, json, headers))
        return self.handler(path, json, headers)

    def get(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(("GET", path, params, headers))
        return self.handler(path, params, headers)

    def close(self) -> None:
        pass


def _status_error(status: int, text: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api-seller.ozon.ru/x")
    response = httpx.Response(status_code=status, request=request, text=text)
    return httpx.HTTPStatusError(str(status), request=request, response=response)


def _seller(handler: Handler) -> tuple[OzonApiClient, _FakeHttp]:
    client = OzonApiClient(client_id="cid", api_key="key")
    client.http.close()
    fake = _FakeHttp(handler)
    client.http = fake  # type: ignore[assignment]
    return client, fake


def test_postings_follow_cursor_and_skip_forbidden_fbo() -> None:
    pages = {
        "": {"postings": [{"posting_number": "A"}], "has_next": True, "cursor": "c1"},
        "c1": {"postings": [{"posting_number": "B"}], "has_next": False, "cursor": "c2"},
    }

    def handler(path: str, body: dict[str, Any] | None, _: Any) -> Any:
        assert body is not None
        if path == endpoints.POSTINGS_FBO_LIST_PATH:
            raise _status_error(403, "forbidden")
        assert path == endpoints.POSTINGS_FBS_LIST_PATH
        assert body["limit"] == endpoints.POSTINGS_PAGE_LIMIT
        assert "offset" not in body
        return pages[body.get("cursor", "")]

    client, fake = _seller(handler)
    postings = client.postings_since(
        datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC), schemas=("fbs", "fbo")
    )

    assert [p["posting_number"] for p in postings] == ["A", "B"]
    fbs_calls = [c for c in fake.calls if c[1] == endpoints.POSTINGS_FBS_LIST_PATH]
    assert fbs_calls[0][2]["filter"] == {  # type: ignore[index]
        "since": "2026-09-01T00:00:00Z",
        "to": "2026-09-02T00:00:00Z",
    }


def test_postings_propagate_removed_method_errors() -> None:
    def handler(path: str, body: Any, _: Any) -> Any:
        raise _status_error(404)

    client, _ = _seller(handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.postings_since(
            datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC), schemas=("fbo",)
        )


def test_postings_split_periods_longer_than_a_year() -> None:
    def handler(path: str, body: Any, _: Any) -> Any:
        return {"postings": [], "has_next": False}

    client, fake = _seller(handler)
    client.postings_since(datetime(2024, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))

    windows = [(c[2]["filter"]["since"], c[2]["filter"]["to"]) for c in fake.calls]  # type: ignore[index]
    assert windows == [
        ("2024-01-01T00:00:00Z", "2024-12-30T00:00:00Z"),
        ("2024-12-30T00:00:00Z", "2025-12-29T00:00:00Z"),
        ("2025-12-29T00:00:00Z", "2026-01-01T00:00:00Z"),
    ]


def test_stocks_follow_cursor_until_total() -> None:
    pages = {
        "": {"items": [{"product_id": 1}], "cursor": "n1", "total": 2},
        "n1": {"items": [{"product_id": 2}], "cursor": "n2", "total": 2},
    }

    def handler(path: str, body: dict[str, Any] | None, _: Any) -> Any:
        assert path == endpoints.STOCKS_PATH
        assert body is not None
        return pages[body.get("cursor", "")]

    client, fake = _seller(handler)

    assert [item["product_id"] for item in client.stocks()] == [1, 2]
    assert len(fake.calls) == 2


def test_fbo_stocks_are_requested_in_sku_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(endpoints, "FBO_STOCKS_SKU_BATCH", 2)

    def handler(path: str, body: dict[str, Any] | None, _: Any) -> Any:
        assert path == endpoints.FBO_STOCKS_PATH
        assert body is not None
        return {"items": [{"sku": int(sku)} for sku in body["skus"]]}

    client, fake = _seller(handler)
    rows = client.fbo_stocks([1, 2, 2, 3, 0])

    assert [row["sku"] for row in rows] == [1, 2, 3]
    assert [call[2]["skus"] for call in fake.calls] == [["1", "2"], ["3"]]  # type: ignore[index]


def test_finance_accruals_follow_last_id_for_one_day() -> None:
    pages = {
        "": {"accruals": [{"accrual_id": 1}, {"accrual_id": 2}], "last_id": "p1"},
        "p1": {"accruals": [{"accrual_id": 3}], "last_id": "p2"},
        "p2": {"accruals": [], "last_id": ""},
    }

    def handler(path: str, body: dict[str, Any] | None, _: Any) -> Any:
        assert path == endpoints.FINANCE_ACCRUAL_BY_DAY_PATH
        assert body is not None
        assert body["date"] == "2026-09-15"
        return pages[body["last_id"]]

    client, fake = _seller(handler)

    records = client.finance_accruals_for_day(date(2026, 9, 15))

    assert [r["accrual_id"] for r in records] == [1, 2, 3]
    assert [call[2]["last_id"] for call in fake.calls] == ["", "p1", "p2"]  # type: ignore[index]


def test_finance_accruals_reject_a_repeated_cursor() -> None:
    def handler(path: str, body: Any, _: Any) -> Any:
        return {"accruals": [{"accrual_id": 1}], "last_id": "same"}

    client, _ = _seller(handler)

    with pytest.raises(RuntimeError, match="twice"):
        client.finance_accruals_for_day(date(2026, 9, 15))


def test_finance_accrual_types_map_ids_to_names() -> None:
    def handler(path: str, body: Any, _: Any) -> Any:
        assert path == endpoints.FINANCE_ACCRUAL_TYPES_PATH
        return {
            "accrual_types": [
                {"id": 1, "name": "Acquiring", "description": "Эквайринг"},
                {"id": 41, "name": "", "description": "Оплата за клик"},
                {"name": "broken"},
            ]
        }

    client, _ = _seller(handler)

    assert client.finance_accrual_types() == {1: "Acquiring", 41: "Оплата за клик"}


def _performance(handler: Handler) -> tuple[OzonPerformanceClient, _FakeHttp]:
    client = OzonPerformanceClient(client_id="perf-id", client_secret="perf-secret")
    client.http.close()
    fake = _FakeHttp(handler)
    client.http = fake  # type: ignore[assignment]
    return client, fake


def test_performance_client_caches_token_and_reads_daily_rows() -> None:
    def handler(path: str, body: dict[str, Any] | None, headers: Any) -> Any:
        if path == endpoints.PERFORMANCE_TOKEN_PATH:
            assert body == {
                "client_id": "perf-id",
                "client_secret": "perf-secret",
                "grant_type": "client_credentials",
            }
            return {"access_token": "tok", "expires_in": 1800, "token_type": "Bearer"}
        assert path == endpoints.PERFORMANCE_DAILY_STATS_PATH
        assert headers["Authorization"] == "Bearer tok"
        return {"rows": [{"id": "1", "date": body["dateFrom"]}]}  # type: ignore[index]

    client, fake = _performance(handler)

    first = client.daily_stats(date(2026, 9, 1), date(2026, 9, 3))
    client.daily_stats(date(2026, 9, 4), date(2026, 9, 4))

    assert first == [{"id": "1", "date": "2026-09-01"}]
    token_calls = [c for c in fake.calls if c[1] == endpoints.PERFORMANCE_TOKEN_PATH]
    assert len(token_calls) == 1
    assert fake.calls[1][2] == {"dateFrom": "2026-09-01", "dateTo": "2026-09-03"}


def test_performance_client_refreshes_a_rejected_token_once() -> None:
    tokens = iter(["old", "new"])

    def handler(path: str, body: Any, headers: Any) -> Any:
        if path == endpoints.PERFORMANCE_TOKEN_PATH:
            return {"access_token": next(tokens), "expires_in": 1800}
        if headers["Authorization"] == "Bearer old":
            raise _status_error(401)
        return {"rows": []}

    client, fake = _performance(handler)

    assert client.daily_stats(date(2026, 9, 1), date(2026, 9, 1)) == []
    assert [c[1] for c in fake.calls].count(endpoints.PERFORMANCE_TOKEN_PATH) == 2


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (403, "", True),
        (400, "Premium Plus subscription required", True),
        (404, "not found", False),
        (405, "method not available", False),
        (400, '{"code": 9, "message": "obsolete method cannot be used"}', False),
        (500, "", False),
    ],
)
def test_capability_errors_exclude_removed_methods(status: int, body: str, expected: bool) -> None:
    assert is_capability_error(_status_error(status, body)) is expected
