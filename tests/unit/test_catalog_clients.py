"""Pagination of the WB and Ozon catalogue methods used by the history store."""

from __future__ import annotations

from typing import Any

import pytest

from collectors.ozon import endpoints as ozon_endpoints
from collectors.ozon.client import OzonApiClient
from collectors.wb import endpoints as wb_endpoints
from collectors.wb.client import WbCatalogClient


class _Http:
    def __init__(self, responder: Any) -> None:
        self.responder = responder
        self.calls: list[tuple[str, Any, Any]] = []

    def post(self, path: str, headers: Any = None, json: Any = None, params: Any = None) -> Any:
        self.calls.append((path, json, headers))
        return self.responder(path, json)

    def get(self, path: str, headers: Any = None, params: Any = None) -> Any:
        self.calls.append((path, params, headers))
        return self.responder(path, params)

    def close(self) -> None:
        pass


def _wb(content: Any = None, prices: Any = None) -> WbCatalogClient:
    client = WbCatalogClient("content-token", "prices-token")
    client.content.close()
    client.prices_http.close()
    client.content = content  # type: ignore[assignment]
    client.prices_http = prices  # type: ignore[assignment]
    return client


def test_wb_cards_follow_the_cursor_until_a_short_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wb_endpoints, "CARDS_PAGE_LIMIT", 2)
    pages = [
        {"cards": [{"nmID": 1}, {"nmID": 2}], "cursor": {"updatedAt": "t2", "nmID": 2, "total": 2}},
        {"cards": [{"nmID": 3}], "cursor": {"updatedAt": "t3", "nmID": 3, "total": 1}},
    ]
    http = _Http(lambda _path, _body: pages[len(http.calls) - 1])
    client = _wb(content=http)

    assert [card["nmID"] for card in client.cards()] == [1, 2, 3]
    (_, first, headers), (_, second, _) = http.calls
    assert headers == {"Authorization": "content-token"}
    assert first["settings"]["cursor"] == {"limit": 2}
    assert second["settings"]["cursor"] == {"limit": 2, "updatedAt": "t2", "nmID": 2}


def test_wb_cards_refuse_a_cursor_that_does_not_advance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wb_endpoints, "CARDS_PAGE_LIMIT", 1)
    stuck = {"cards": [{"nmID": 1}], "cursor": {"updatedAt": "t", "nmID": 1, "total": 1}}
    client = _wb(content=_Http(lambda *_: stuck))

    with pytest.raises(RuntimeError, match="same cursor"):
        client.cards()


def test_wb_prices_page_by_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wb_endpoints, "PRICES_PAGE_LIMIT", 2)

    def respond(_path: str, params: dict[str, Any]) -> Any:
        goods = [{"nmID": n} for n in range(params["offset"], min(params["offset"] + 2, 3))]
        return {"data": {"listGoods": goods}}

    http = _Http(respond)
    client = _wb(prices=http)

    assert [item["nmID"] for item in client.prices()] == [0, 1, 2]
    assert http.calls[0][2] == {"Authorization": "prices-token"}


def _ozon(responder: Any) -> tuple[OzonApiClient, _Http]:
    client = OzonApiClient("id", "key")
    client.http.close()
    http = _Http(responder)
    client.http = http  # type: ignore[assignment]
    return client, http


def test_ozon_product_ids_page_with_last_id() -> None:
    pages = {
        "": {"result": {"items": [{"product_id": 1}, {"product_id": 2}], "last_id": "a"}},
        "a": {"result": {"items": [{"product_id": 3}], "last_id": "b"}},
        "b": {"result": {"items": [], "last_id": ""}},
    }
    client, _ = _ozon(lambda _path, body: pages[body["last_id"]])

    assert client.product_ids() == [1, 2, 3]


def test_ozon_product_info_batches_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ozon_endpoints, "PRODUCT_BATCH", 2)
    client, http = _ozon(
        lambda _path, body: {"items": [{"id": int(pid)} for pid in body["product_id"]]}
    )

    items = client.product_info([1, 2, 3])

    assert [item["id"] for item in items] == [1, 2, 3]
    assert [call[1]["product_id"] for call in http.calls] == [["1", "2"], ["3"]]


def test_ozon_attributes_and_prices_follow_their_cursors() -> None:
    def respond(path: str, body: dict[str, Any]) -> Any:
        if path == ozon_endpoints.PRODUCT_ATTRIBUTES_PATH:
            if body["last_id"] == "":
                return {"result": [{"id": 1}], "last_id": "x"}
            return {"result": [{"id": 2}], "last_id": ""}
        assert path == ozon_endpoints.PRODUCT_PRICES_PATH
        if body["cursor"] == "":
            return {"items": [{"product_id": 1}], "cursor": "c"}
        return {"items": [], "cursor": ""}

    client, http = _ozon(respond)

    assert [a["id"] for a in client.product_attributes([1, 2])] == [1, 2]
    assert [p["product_id"] for p in client.product_prices([1, 2])] == [1]
    assert all(call[1]["filter"]["product_id"] == ["1", "2"] for call in http.calls)
