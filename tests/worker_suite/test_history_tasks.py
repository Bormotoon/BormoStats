"""Catalogue snapshot tasks: what they read, what they commit, when they skip."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from app.tasks import history

from tests.worker_suite.test_history_store import MemoryClickHouse


class _WbClient:
    prices_error: Exception | None = None

    def __init__(self, content_token: str, prices_token: str = "") -> None:
        self.prices_token = prices_token

    def __enter__(self) -> _WbClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def cards(self) -> list[dict[str, Any]]:
        return [{"nmID": 1, "title": "Mug"}]

    def prices(self) -> list[dict[str, Any]]:
        if self.prices_error is not None:
            raise self.prices_error
        return [{"nmID": 1, "sizes": [{"price": 1000}]}]


@contextmanager
def _no_lock(**_: Any) -> Any:
    class Handle:
        def ensure_held(self) -> None:
            pass

    yield Handle()


@pytest.fixture
def ch(monkeypatch: pytest.MonkeyPatch) -> MemoryClickHouse:
    client = MemoryClickHouse()
    monkeypatch.setattr(history, "get_ch_client", lambda: client)
    monkeypatch.setattr(history, "get_redis_client", lambda: object())
    monkeypatch.setattr(history, "lock_scope", _no_lock)
    monkeypatch.setattr(history, "log_task_run", lambda *a, **k: None)
    monkeypatch.setattr(history, "WbCatalogClient", _WbClient)
    _WbClient.prices_error = None
    monkeypatch.setenv("WB_TOKEN_CONTENT", "c")
    monkeypatch.setenv("WB_TOKEN_PRICES", "p")
    return client


def test_wb_snapshot_commits_cards_with_prices(ch: MemoryClickHouse) -> None:
    report = history.wb_catalog_snapshot("acc")

    assert report["status"] == "success" and report["created"] == 1
    [ref] = ch.rows("hist_refs")
    assert (ref["marketplace"], ref["repo"], ref["entity_key"]) == ("wb", "product", "1")
    assert history.wb_catalog_snapshot("acc")["unchanged"] == 1


def test_wb_snapshot_skips_without_content_token(
    ch: MemoryClickHouse, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WB_TOKEN_CONTENT")

    assert history.wb_catalog_snapshot("acc") == {
        "status": "skipped",
        "reason": "missing WB_TOKEN_CONTENT",
    }
    assert ch.inserts == []


def test_wb_snapshot_keeps_recorded_price_when_prices_are_forbidden(ch: MemoryClickHouse) -> None:
    history.wb_catalog_snapshot("acc")
    request = httpx.Request("GET", "https://discounts-prices-api.wildberries.ru/x")
    _WbClient.prices_error = httpx.HTTPStatusError(
        "forbidden", request=request, response=httpx.Response(403, request=request)
    )

    report = history.wb_catalog_snapshot("acc")

    assert report["status"] == "success" and report["modified"] == 0 and report["deleted"] == 0
    assert len(ch.rows("hist_commits")) == 1


def test_wb_snapshot_fails_loudly_when_the_prices_method_is_gone(ch: MemoryClickHouse) -> None:
    request = httpx.Request("GET", "https://discounts-prices-api.wildberries.ru/x")
    _WbClient.prices_error = httpx.HTTPStatusError(
        "gone", request=request, response=httpx.Response(404, request=request)
    )

    with pytest.raises(httpx.HTTPStatusError):
        history.wb_catalog_snapshot("acc")
    assert ch.inserts == []


def test_backfill_task_imports_only_tables_not_yet_done(
    ch: MemoryClickHouse, monkeypatch: pytest.MonkeyPatch
) -> None:
    ch.done_sources = {
        history_source
        for history_source in (f"history_backfill_done:{t}" for t in history.STAT_SPECS)
        if not history_source.endswith("raw_wb_sales")
    }
    imported: list[str] = []
    monkeypatch.setattr(
        history,
        "backfill_table",
        lambda _client, table, run_id: imported.append(table) or {"rows": 0, "commits": 0},
    )

    report = history.backfill_raw_archive()

    assert imported == ["raw_wb_sales"]
    assert report["status"] == "success"
