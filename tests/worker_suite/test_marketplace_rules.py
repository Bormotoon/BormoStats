from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.tasks.bidder import BidRule, bid_executor, plan_bid_change
from app.tasks.repricer import (
    PriceRule,
    PriceSnapshot,
    desired_price,
    plan_price_change,
    price_executor,
    step_limited,
)
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


NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


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
        "mode": "buyer_price",
        "target_price": 400.0,
        "max_step_pct": 10.0,
    }
    data.update(overrides)
    return PriceRule(**data)  # type: ignore[arg-type]


def _snap(**overrides: object) -> PriceSnapshot:
    data: dict[str, object] = {
        "product_id": "1001",
        "list_price": 1000.0,
        "seller_discount_pct": 50.0,
        "seller_price": 500.0,
        "mp_discount_pct": 20.0,
        "mp_discount_scope": "product",
        "mp_discount_samples": 5,
        "breakeven_price": 300.0,
        "price_seen_at": NOW - timedelta(hours=1),
    }
    data.update(overrides)
    return PriceSnapshot(**data)  # type: ignore[arg-type]


def test_buyer_price_compensates_the_marketplace_discount() -> None:
    # the buyer pays 400 at a 20 % marketplace discount when the seller price is 500
    assert desired_price(_price_rule(), _snap()).price == 500
    assert desired_price(_price_rule(target_price=480.0), _snap()).price == 600


@pytest.mark.parametrize(
    ("marketplace", "snap"),
    [
        ("ozon", _snap(mp_discount_scope="account")),
        ("ozon", _snap(mp_discount_pct=None, mp_discount_scope="")),
        ("wb", _snap(mp_discount_samples=2)),
    ],
)
def test_buyer_price_needs_the_cards_own_discount(marketplace: str, snap: PriceSnapshot) -> None:
    decision = desired_price(_price_rule(marketplace=marketplace), snap)
    assert decision.price is None and decision.reason == "no_discount_data"


def test_ozon_prices_on_the_cards_discount_from_its_first_sale() -> None:
    # Ozon's points discount is the card's own: one sale at 50 % off doubles the seller price,
    # or buyers would pay half the desired price
    rule = _price_rule(no_discount_fallback="seller_price")
    one = desired_price(rule, _snap(mp_discount_pct=50.0, mp_discount_samples=1))
    assert (one.price, one.fallback) == (800, "")


def test_ozon_red_price_index_lowers_the_price_down_to_the_target() -> None:
    # the measured 50 % asks for 800, but Ozon rates 800 above the market and cuts its points
    rule = _price_rule(target_price=400.0)
    red = desired_price(
        rule, _snap(seller_price=800.0, mp_discount_pct=50.0, price_index_color="RED")
    )
    assert (red.price, red.index_guard) == (720, "RED")  # one 10 % step down
    # never below the desired price: there the buyer pays it even without Ozon's points
    near = _snap(seller_price=420.0, mp_discount_pct=50.0, price_index_color="RED")
    assert desired_price(rule, near).price == 400
    # a rule asking for less than the step goes there directly
    low = _snap(seller_price=800.0, mp_discount_pct=20.0, price_index_color="RED")
    assert desired_price(rule, low).price == 500

    yellow = _snap(seller_price=700.0, mp_discount_pct=50.0, price_index_color="YELLOW")
    held = desired_price(rule, yellow)
    assert (held.price, held.index_guard) == (700, "YELLOW")
    assert plan_price_change(rule, yellow, now=NOW) == (None, "in_tolerance")
    # YELLOW still lets the price go down, GREEN lets it go up; WB has no Ozon index
    down = _snap(seller_price=900.0, mp_discount_pct=50.0, price_index_color="YELLOW")
    assert desired_price(rule, down).price == 800
    green = _snap(seller_price=700.0, mp_discount_pct=50.0, price_index_color="GREEN")
    assert desired_price(rule, green).price == 800
    wb_red = _snap(seller_price=700.0, mp_discount_pct=50.0, price_index_color="RED")
    assert desired_price(_price_rule(marketplace="wb", target_price=400.0), wb_red).price == 800
    # a seller-price rule keeps its price whatever the index
    seller = _price_rule(mode="seller_price", target_price=800.0)
    assert desired_price(seller, _snap(seller_price=800.0, price_index_color="RED")).price == 800


def test_wb_may_use_the_accounts_spp() -> None:
    wb = _price_rule(marketplace="wb")
    account = _snap(mp_discount_scope="account", mp_discount_samples=12)
    assert desired_price(wb, account).price == 500
    few = desired_price(wb, _snap(mp_discount_scope="account", mp_discount_samples=9))
    assert few.price is None and few.reason == "no_discount_data"
    # Ozon's discounts vary between cards: the account's median is never used
    assert desired_price(_price_rule(), account).price is None


def test_no_discount_fallbacks() -> None:
    no_sales = _snap(mp_discount_scope="account", mp_discount_samples=0, mp_discount_pct=50.0)
    # by default the rule waits for the card's own sales
    assert desired_price(_price_rule(), no_sales).reason == "no_discount_data"
    wb_median = _price_rule(marketplace="wb", no_discount_fallback="account_median")
    median = desired_price(wb_median, no_sales)
    assert (median.price, median.fallback) == (800, "account_median")
    seller = desired_price(_price_rule(no_discount_fallback="seller_price"), no_sales)
    assert (seller.price, seller.fallback) == (400, "seller_price")
    # the account's median is needed for it; the card's own discount wins over a fallback
    nothing = _snap(mp_discount_pct=None, mp_discount_scope="")
    assert desired_price(wb_median, nothing).price is None
    own = desired_price(_price_rule(no_discount_fallback="seller_price"), _snap())
    assert (own.price, own.fallback) == (500, "")


def test_wb_seller_price_until_three_sales_then_the_measured_discount() -> None:
    rule = _price_rule(marketplace="wb", no_discount_fallback="seller_price")
    two = desired_price(rule, _snap(mp_discount_samples=2))
    assert (two.price, two.fallback) == (400, "seller_price")
    three = desired_price(rule, _snap(mp_discount_samples=3))
    assert (three.price, three.fallback) == (500, "")  # 400 / (1 - 20 %)


def test_ozon_never_prices_on_the_accounts_median() -> None:
    # Ozon gives its discount per card: an account_median rule keeps the target as seller price
    ozon_median = _price_rule(no_discount_fallback="account_median")
    for snap in (
        _snap(mp_discount_scope="account", mp_discount_samples=0, mp_discount_pct=50.0),
        _snap(mp_discount_pct=None, mp_discount_scope=""),
    ):
        decision = desired_price(ozon_median, snap)
        assert (decision.price, decision.fallback) == (400, "seller_price")


def test_other_modes_and_bounds() -> None:
    assert desired_price(_price_rule(mode="seller_price", target_price=450.0), _snap()).price == 450
    assert desired_price(_price_rule(mode="margin"), _snap()).price == 360  # 300 + 20 %
    no_cost = desired_price(_price_rule(mode="margin"), _snap(breakeven_price=None))
    assert no_cost.price is None and no_cost.reason == "no_cost"
    # never below break-even or min_price, never above max_price
    low = desired_price(_price_rule(mode="seller_price", target_price=200.0), _snap())
    assert low.price == 300 and low.clamped_to_min
    assert desired_price(_price_rule(min_price=550.0), _snap()).price == 550
    assert desired_price(_price_rule(max_price=480.0), _snap()).price == 480


def test_step_limit_and_tolerance() -> None:
    assert step_limited(500.0, 700.0, 10.0) == 550
    assert step_limited(500.0, 300.0, 10.0) == 450
    assert step_limited(500.0, 520.0, 10.0) == 520
    action, reason = plan_price_change(_price_rule(target_price=480.0), _snap(), now=NOW)
    assert action is not None and reason == "planned"
    assert (action.before_value, action.after_value, action.target_id) == (500.0, 550.0, "SKU-1")
    # 401.6 / 0.8 = 502: within half a percent of the current price
    assert plan_price_change(_price_rule(target_price=401.6), _snap(), now=NOW) == (
        None,
        "in_tolerance",
    )


def test_stale_or_missing_snapshot_is_not_acted_upon() -> None:
    stale = _snap(price_seen_at=NOW - timedelta(hours=7))
    assert plan_price_change(_price_rule(), stale, now=NOW) == (None, "stale_snapshot")
    assert plan_price_change(_price_rule(), None, now=NOW) == (None, "no_snapshot")


def test_wb_price_keeps_the_cards_discount() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"id": 1}, "error": False})

    wb = WbActionsClient(prices_token="tok")
    _mock(wb, "_prices", handler)
    rule = _price_rule(marketplace="wb", target_price=480.0)
    snap = _snap()
    action, _ = plan_price_change(rule, snap, now=NOW)
    assert action is not None
    executor = price_executor(wb, OzonActionsClient(), rule, snap, action)
    assert executor is not None and executor().ok
    # seller price 550 at the card's 50 % discount is a list price of 1100
    assert seen == [{"data": [{"nmID": 1001, "price": 1100, "discount": 50}]}]


def test_ozon_price_scales_the_crossed_out_price() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"result": [{"offer_id": "SKU-1", "updated": True}]})

    ozon = OzonActionsClient(client_id="c", api_key="k")
    _mock(ozon, "_http", handler)
    rule = _price_rule(target_price=480.0)
    snap = _snap()
    action, _ = plan_price_change(rule, snap, now=NOW)
    assert action is not None
    executor = price_executor(WbActionsClient(), ozon, rule, snap, action)
    assert executor is not None and executor().ok
    # the limit price follows the price, so promotions cannot sell the card below it
    assert seen[0]["prices"] == [
        {
            "offer_id": "SKU-1",
            "price": "550.00",
            "old_price": "1100.00",
            "currency_code": "RUB",
            "min_price": "550.00",
        }
    ]
    assert price_executor(WbActionsClient(), OzonActionsClient(), rule, snap, action) is None


def test_ozon_raises_a_limit_price_under_the_kept_price() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"result": [{"offer_id": "SKU-1", "updated": True}]})

    ozon = OzonActionsClient(client_id="c", api_key="k")
    _mock(ozon, "_http", handler)
    rule = _price_rule()
    # the price is right (400 at 20 % off), but a promotion could take the card down to 300
    snap = _snap(price_limit=300.0)
    action, reason = plan_price_change(rule, snap, now=NOW)
    assert action is not None and reason == "price_limit"
    assert (action.target_type, action.before_value, action.after_value) == (
        "price_limit",
        300.0,
        500.0,
    )
    executor = price_executor(WbActionsClient(), ozon, rule, snap, action)
    assert executor is not None and executor().ok
    assert seen[0]["prices"] == [
        {
            "offer_id": "SKU-1",
            "price": "500.00",
            "old_price": "1000.00",
            "currency_code": "RUB",
            "min_price": "500.00",
        }
    ]

    # a limit at the price, or within the tolerance, is left alone; WB has no limit price
    assert plan_price_change(rule, _snap(price_limit=500.0), now=NOW) == (None, "in_tolerance")
    assert plan_price_change(rule, _snap(price_limit=498.0), now=NOW) == (None, "in_tolerance")
    assert plan_price_change(rule, _snap(price_limit=None), now=NOW) == (None, "in_tolerance")
    wb = _price_rule(marketplace="wb")
    assert plan_price_change(wb, _snap(price_limit=300.0), now=NOW) == (None, "in_tolerance")
    # a rule that waits for the card's discount does not touch the limit either
    waiting = _snap(mp_discount_pct=None, mp_discount_scope="", price_limit=300.0)
    assert plan_price_change(rule, waiting, now=NOW) == (None, "no_discount_data")


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
