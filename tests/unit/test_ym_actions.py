from __future__ import annotations

from typing import Any

from collectors.marketplace_actions import YmActionsClient


def test_stock_update_targets_partner_warehouse() -> None:
    class Http:
        def __init__(self) -> None:
            self.path = ""
            self.body: dict[str, Any] = {}

        def post(self, path: str, *, headers: Any, json: dict[str, Any]) -> dict[str, str]:
            self.path = path
            self.body = json
            return {"status": "OK"}

        def close(self) -> None:
            pass

    client = YmActionsClient(api_key="key", business_id="1", campaign_id="2")
    client._http.close()
    http = Http()
    client._http = http  # type: ignore[assignment]
    assert client.set_stocks(77, [("sku-1", 9)]).ok
    assert http.path == "/v3/businesses/1/offers/stocks/update"
    assert http.body["skuItems"][0]["partnerWarehouseId"] == 77
    assert http.body["skuItems"][0]["count"] == 9
    client.close()


def test_bid_outside_market_limits_is_rejected() -> None:
    with YmActionsClient(api_key="key", business_id="1") as client:
        assert not client.set_bids([("sku", 0.49)]).ok
        assert not client.set_bids([("sku", 100)]).ok
