from __future__ import annotations

import json

import httpx
import pytest
from app.tasks.bidder import BidRule, bid_executor, plan_bid_change
from app.tasks.repricer import Breakeven, PriceRule, plan_price_change, target_price
from app.utils.marketplace_actions import (
    STATUS_APPLIED,
    STATUS_BLOCKED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_SIMULATED,
    STATUS_UNSUPPORTED,
    PlannedAction,
    execute_action,
)

from collectors.marketplace_actions import ActionResult, OzonActionsClient, WbActionsClient
from tests.fakes import FakeClickHouse


def _bid_rule(**overrides: object) -> BidRule:
    data: dict[str, object] = {
        "rule_id": "r1",
        "organization_id": "org-a",
        "campaign_id": "12345",
        "marketplace": "wb",
        "account_id": "default",
        "target_cpm": 250.0,
        "max_cpm": 200.0,
        "product_id": "13335157",
        "placement": "combined",
        "dry_run": True,
    }
    data.update(overrides)
    return BidRule(**data)  # type: ignore[arg-type]


def test_bid_plan_clamps_to_max_and_skips_noops() -> None:
    action = plan_bid_change(_bid_rule(), current=150.0)
    assert action is not None
    assert action.after_value == 200.0 and action.before_value == 150.0
    assert plan_bid_change(_bid_rule(), current=200.0) is None
    assert plan_bid_change(_bid_rule(), current=None) is None


def _price_rule(**overrides: object) -> PriceRule:
    data: dict[str, object] = {
        "rule_id": "p1",
        "organization_id": "org-a",
        "marketplace": "ozon",
        "account_id": "default",
        "product_id": "SKU-1",
        "min_price": 0.0,
        "max_price": 0.0,
        "target_margin_percent": 20.0,
        "dry_run": False,
    }
    data.update(overrides)
    return PriceRule(**data)  # type: ignore[arg-type]


def test_price_target_respects_margin_and_bounds() -> None:
    be = Breakeven(breakeven_price=100.0, current_price=100.0)
    assert target_price(_price_rule(), be) == (120.0, False)
    assert target_price(_price_rule(min_price=150.0), be) == (150.0, True)
    assert target_price(_price_rule(max_price=110.0), be) == (110.0, False)
    assert plan_price_change(_price_rule(), Breakeven(100.0, 120.5)) is None


def _action(dry_run: bool = False) -> PlannedAction:
    return PlannedAction(
        organization_id="org-a",
        source="repricer",
        rule_id="p1",
        marketplace="ozon",
        account_id="default",
        target_type="price",
        target_id="SKU-1",
        before_value=100.0,
        after_value=120.0,
        dry_run=dry_run,
    )


def _ok() -> ActionResult:
    return ActionResult(ok=True, status_code=200, body="{}")


def test_dry_run_only_simulates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETPLACE_ACTIONS_ENABLED", "true")
    ch = FakeClickHouse()
    calls: list[int] = []
    status = execute_action(ch, _action(dry_run=True), lambda: calls.append(1) or _ok())
    assert status == STATUS_SIMULATED and calls == []
    ((_, params),) = ch.commands_matching("INSERT INTO sys_marketplace_actions")
    assert params["dry_run"] == 1 and params["before_value"] == 100.0


def test_kill_switch_blocks_live_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKETPLACE_ACTIONS_ENABLED", raising=False)
    calls: list[int] = []
    status = execute_action(FakeClickHouse(), _action(), lambda: calls.append(1) or _ok())
    assert status == STATUS_BLOCKED and calls == []


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (ActionResult(True, 200, "{}"), STATUS_APPLIED),
        (ActionResult(False, 500, "boom"), STATUS_FAILED),
    ],
)
def test_live_changes_are_audited(
    monkeypatch: pytest.MonkeyPatch, result: ActionResult, expected: str
) -> None:
    monkeypatch.setenv("MARKETPLACE_ACTIONS_ENABLED", "1")
    ch = FakeClickHouse()
    assert execute_action(ch, _action(), lambda: result) == expected
    ((_, params),) = ch.commands_matching("INSERT INTO sys_marketplace_actions")
    assert params["status"] == expected
    assert params["response_status"] == result.status_code
    assert len(params["idempotency_key"]) == 64


def test_unsupported_and_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETPLACE_ACTIONS_ENABLED", "1")
    assert execute_action(FakeClickHouse(), _action(), None) == STATUS_UNSUPPORTED
    seen = FakeClickHouse().on("FROM sys_marketplace_actions", [{"count()": 1}])
    assert execute_action(seen, _action(), lambda: _ok()) == STATUS_DUPLICATE
    assert seen.commands == []


def _mock(client: object, attr: str, handler: object) -> None:
    http = getattr(client, attr)
    http._client = httpx.Client(base_url=http.base_url, transport=httpx.MockTransport(handler))


def test_wb_bid_request_matches_api_contract() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"bids": [], "currency": "RUB"})

    wb = WbActionsClient(promotion_token="tok")
    _mock(wb, "_advert", handler)
    rule = _bid_rule(dry_run=False)
    action = plan_bid_change(rule, current=150.0)
    assert action is not None
    executor = bid_executor(wb, rule, action)
    assert executor is not None and executor().ok
    request = seen[0]
    assert request.method == "PATCH" and request.url.path == "/api/advert/v1/bids"
    assert request.headers["Authorization"] == "tok"
    assert json.loads(request.content) == {
        "bids": [
            {
                "advert_id": 12345,
                "nm_bids": [{"nm_id": 13335157, "bid_kopecks": 20000, "placement": "combined"}],
            }
        ]
    }
    assert bid_executor(WbActionsClient(), rule, action) is None  # no promotion token


def test_ozon_price_failure_is_reported_per_item() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["prices"][0] == {
            "offer_id": "SKU-1",
            "price": "120.00",
            "old_price": "0",
            "currency_code": "RUB",
        }
        return httpx.Response(
            200, json={"result": [{"offer_id": "SKU-1", "updated": False, "errors": ["x"]}]}
        )

    ozon = OzonActionsClient(client_id="c", api_key="k")
    _mock(ozon, "_http", handler)
    result = ozon.set_price("SKU-1", 120.0)
    assert not result.ok and "SKU-1" in result.body


def test_wb_stock_update_uses_marketplace_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/api/v3/stocks/507"
        assert json.loads(request.content) == {"stocks": [{"chrtId": 11, "amount": 3}]}
        return httpx.Response(204)

    wb = WbActionsClient(marketplace_token="tok")
    _mock(wb, "_marketplace", handler)
    assert wb.set_stocks(507, [(11, 3)]).ok
