from __future__ import annotations

from types import SimpleNamespace

from app.models.integrations import StockUpdateItem
from app.services.integrations_service import IntegrationsService

from tests.fakes import FakeClickHouse


def _settings(**updates: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "marketplace_actions_enabled": True,
        "ym_account_id": "acct",
        "ym_campaign_id": "campaign-1",
        "ym_business_id": "business-1",
        "ym_api_key": "not-used",
        "ym_stock_mode": "grouped",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_grouped_stock_rejects_duplicate_sku_and_fake_warehouse(monkeypatch) -> None:
    ch = FakeClickHouse().on("SELECT count() FROM dim_account", [{"count()": 1}])
    service = IntegrationsService(ch, _settings(), "org")
    monkeypatch.setattr("app.services.integrations_service.YmActionsClient", lambda **_: None)
    duplicate = service._push_ym_stock(
        [StockUpdateItem(sku="a", stock=3), StockUpdateItem(sku="a", stock=4)]
    )
    assert not duplicate.success and "Duplicate SKU" in duplicate.errors[0]
    fake_warehouse = service._push_ym_stock([StockUpdateItem(sku="a", stock=3, warehouse_id=7)])
    assert not fake_warehouse.success and "warehouse_id is not accepted" in fake_warehouse.errors[0]


def test_configured_partner_warehouse_sends_to_exact_validated_destination(monkeypatch) -> None:
    ch = (
        FakeClickHouse()
        .on("SELECT count() FROM dim_account", [{"count()": 1}])
        .on("SELECT DISTINCT warehouse_id FROM raw_ym_stocks", [{"warehouse_id": 9}])
    )
    sent: list[tuple[int, list[tuple[str, int]]]] = []

    class Client:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def set_stocks(self, warehouse: int, items: list[tuple[str, int]]) -> SimpleNamespace:
            sent.append((warehouse, items))
            return SimpleNamespace(ok=True)

    monkeypatch.setattr("app.services.integrations_service.YmActionsClient", Client)
    service = IntegrationsService(ch, _settings(ym_stock_mode="partner"), "org")
    result = service._push_ym_stock([StockUpdateItem(sku="book-01", stock=0, warehouse_id=9)])
    assert result.success and sent == [(9, [("book-01", 0)])]


def test_partner_stock_checks_campaign_owned_warehouse_before_call(monkeypatch) -> None:
    ch = (
        FakeClickHouse()
        .on("SELECT count() FROM dim_account", [{"count()": 1}])
        .on("SELECT DISTINCT warehouse_id FROM raw_ym_stocks", [{"warehouse_id": 9}])
    )
    calls: list[object] = []

    class NeverClient:
        def __init__(self, **_: object) -> None:
            calls.append("client")

        def __enter__(self) -> NeverClient:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr("app.services.integrations_service.YmActionsClient", NeverClient)
    service = IntegrationsService(ch, _settings(ym_stock_mode="partner"), "org")
    result = service._push_ym_stock([StockUpdateItem(sku="a", stock=2, warehouse_id=77)])
    assert not result.success and calls == []
