"""Price breakdown end to end: catalogue snapshots, sales and fees -> mrt_price_current -> API,
and a desired price turned into a dry-run repricer action."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.tasks import marts, repricer, transforms
from app.utils.history_store import HistoryStore, Observation
from app.utils.runtime import log_task_run

ACCOUNT = "default"


def _wb_card() -> dict[str, Any]:
    return {
        "card": {"nmID": 1001, "vendorCode": "btn1", "title": "Button"},
        "price": {"nmID": 1001, "discount": 50, "sizes": [{"price": 1000, "discountedPrice": 500}]},
    }


def _ozon_card() -> dict[str, Any]:
    return {
        "info": {"id": 77, "sku": 2002, "offer_id": "btn1", "name": "Button"},
        "price": {
            "offer_id": "btn1",
            "acquiring": 8,
            "commissions": {
                "sales_percent_fbo": 40,
                "sales_percent_fbs": 45,
                "fbo_direct_flow_trans_min_amount": 50,
                "fbo_deliv_to_customer_amount": 25,
            },
            "price": {
                "price": 800,
                "old_price": 1600,
                "min_price": 500,
                "auto_action_enabled": False,
            },
        },
    }


def _seed(client: Any, now: datetime) -> None:
    for marketplace, key, doc in (("wb", "1001", _wb_card()), ("ozon", "77", _ozon_card())):
        HistoryStore(client, run_id=str(uuid4()), source="it").record(
            marketplace=marketplace,
            account_id=ACCOUNT,
            repo="product",
            observations=[Observation(key, doc, now - timedelta(minutes=30))],
        )
        log_task_run(
            client,
            f"tasks.history.{marketplace}_catalog_snapshot",
            str(uuid4()),
            now - timedelta(minutes=31),
            "success",
            1,
            "catalogue snapshot",
        )
    # WB orders: the buyer paid 400, 400, 350, 400 for a seller price of 500 -> median 20 %
    client.insert(
        "raw_wb_orders",
        [
            [
                now,
                ACCOUNT,
                f"srid-{i}",
                now - timedelta(hours=i + 1),
                now - timedelta(hours=i + 1),
                1001,
                1,
                1,
                500.0,
                json.dumps({"priceWithDisc": 500, "finishedPrice": paid, "isCancel": False}),
            ]
            for i, paid in enumerate((400, 400, 350, 400))
        ],
        column_names=[
            "ingested_at",
            "account_id",
            "srid",
            "last_change_ts",
            "event_ts",
            "nm_id",
            "chrt_id",
            "quantity",
            "price_rub",
            "payload",
        ],
    )
    # WB realization report: 2 units sold for 1000, commission 300 + acquiring 20, delivery 140
    today = now.date()
    client.insert(
        "raw_wb_sales_report",
        [
            [
                now,
                ACCOUNT,
                1,
                today,
                1001,
                "Продажа",
                "Продажа",
                2,
                1000.0,
                -300.0,
                -20.0,
                0.0,
                "{}",
            ],
            [now, ACCOUNT, 2, today, 1001, "", "Логистика", 0, 0.0, 0.0, 0.0, -140.0, "{}"],
        ],
        column_names=[
            "ingested_at",
            "account_id",
            "rrd_id",
            "day",
            "nm_id",
            "doc_type",
            "oper_name",
            "quantity",
            "sales",
            "commission",
            "acquiring",
            "logistics",
            "payload",
        ],
    )
    # Ozon sale accruals: seller price 800, the buyer paid 400 (Ozon paid the rest), delivery 90
    line = {
        "sku": 2002,
        "quantity": 1,
        "commission": {
            "seller_price": {"amount": "800"},
            "sale_price": {"amount": "400"},
            "bonus": {"amount": "400"},
        },
        "delivery": {"total_accrued": {"amount": "-90"}},
    }
    client.insert(
        "raw_ozon_finance_ops",
        [
            [
                now,
                ACCOUNT,
                f"op-{i}",
                now - timedelta(days=i + 1),
                "posting",
                310.0,
                "RUB",
                json.dumps({"posting": {"delivery_schema": "Fbo", "products": [line]}}),
                "accrual_by_day",
            ]
            for i in range(3)
        ],
        column_names=[
            "ingested_at",
            "account_id",
            "operation_id",
            "operation_ts",
            "type",
            "amount",
            "currency",
            "payload",
            "source",
        ],
    )


def test_price_breakdown_compare_and_target(integration_runtime: Any, api_client: Any) -> None:
    client = integration_runtime.ch_client()
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        _seed(client, now)
        assert api_client.put("/api/v1/pricing/costs/btn1", json={"cost_price_rub": 100}).is_success
        assert transforms.transform_all_recent()["status"] == "success"
        assert marts.build_marts_recent()["status"] == "success"

        response = api_client.get("/api/v1/pricing/breakdown")
        assert response.status_code == 200, response.text
        rows = {row["marketplace"]: row for row in response.json()}
        wb, ozon = rows["wb"], rows["ozon"]

        assert wb["offer_id"] == "btn1" and wb["product_id"] == "1001"
        assert (wb["list_price"], wb["seller_discount_pct"], wb["seller_price"]) == (1000, 50, 500)
        assert (wb["mp_discount_pct"], wb["mp_discount_scope"]) == (20, "product")
        assert wb["mp_discount_samples"] == 4 and wb["buyer_price"] == 400
        assert (wb["commission_pct"], wb["commission_rub"], wb["logistics_rub"]) == (32, 160, 70)
        assert (wb["cost_price"], wb["margin_rub"], wb["margin_pct"]) == (100, 170, 34)
        assert wb["breakeven_price"] == pytest.approx(250, abs=0.01)  # (100 + 70) / 0.68

        assert ozon["product_id"] == "2002" and ozon["seller_price"] == 800
        assert (ozon["list_price"], ozon["seller_discount_pct"]) == (1600, 50)
        assert (ozon["mp_discount_pct"], ozon["buyer_price"]) == (50, 400)
        assert (ozon["commission_pct"], ozon["commission_rub"]) == (40, 320)  # FBO tariff
        assert (ozon["acquiring_rub"], ozon["logistics_rub"], ozon["fees_rub"]) == (8, 90, 418)
        assert (ozon["margin_rub"], ozon["margin_pct"]) == (282, 35.25)
        assert ozon["breakeven_price"] == 330  # (100 + 8 + 90) / 0.6
        assert ozon["min_price"] == 500 and ozon["auto_actions_enabled"] is False

        compare = api_client.get("/api/v1/pricing/compare").json()
        assert compare == [
            {
                "offer_id": "btn1",
                "title": "Button",
                "image_url": None,
                "wb_seller_price": 500.0,
                "wb_buyer_price": 400.0,
                "ozon_seller_price": 800.0,
                "ozon_buyer_price": 400.0,
                "buyer_spread_pct": 0.0,
            }
        ]

        # the desired buyer price 480 at a 20 % discount needs a seller price of 600
        rule = api_client.put("/api/v1/pricing/target/wb/btn1", json={"target_price": 480})
        assert rule.status_code == 200, rule.text
        assert rule.json()["dry_run"] is True and rule.json()["mode"] == "buyer_price"
        # a new WB rule waits for sales to measure the discount
        assert rule.json()["no_discount_fallback"] == ""
        again = api_client.put(
            "/api/v1/pricing/target/wb/btn1", json={"target_price": 450, "max_step_pct": 5}
        )
        assert again.json()["rule_id"] == rule.json()["rule_id"]
        wb = next(
            r
            for r in api_client.get("/api/v1/pricing/breakdown").json()
            if r["marketplace"] == "wb"
        )
        assert wb["target_price"] == 450 and wb["target_gap_pct"] == pytest.approx(-11.11)

        result = repricer.repricer_evaluate_rules()
        assert result["status"] == "success" and result["simulated"] == 1, result
        action = client.query(
            "SELECT target_id, before_value, after_value, dry_run, status"
            " FROM sys_marketplace_actions WHERE source = 'repricer'"
        ).result_rows
        # 450 / 0.8 = 562.5 -> 562, but one step is 5 % of 500
        assert action == [("btn1", 500.0, 525.0, 1, "simulated")]

        # a new Ozon rule keeps the desired price as the seller price until 3 sales
        imported = api_client.post(
            "/api/v1/pricing/targets/import", json={"marketplace": "ozon", "text": "btn1;690"}
        )
        assert imported.json()["imported"] == 1, imported.text
        ozon = next(
            r
            for r in api_client.get("/api/v1/pricing/breakdown").json()
            if r["marketplace"] == "ozon"
        )
        assert (ozon["target_price"], ozon["no_discount_fallback"]) == (690, "seller_price")

        # a fallback for a card without sales is kept when the price changes, and shown
        fallback = api_client.put(
            "/api/v1/pricing/target/ozon/btn1",
            json={"target_price": 700, "no_discount_fallback": "seller_price"},
        )
        assert fallback.status_code == 200, fallback.text
        assert fallback.json()["no_discount_fallback"] == "seller_price"
        kept = api_client.put("/api/v1/pricing/target/ozon/btn1", json={"target_price": 720})
        assert kept.json()["no_discount_fallback"] == "seller_price"
        ozon = next(
            r
            for r in api_client.get("/api/v1/pricing/breakdown").json()
            if r["marketplace"] == "ozon"
        )
        assert ozon["no_discount_fallback"] == "seller_price"
        # Ozon gives its discount per card: the account's median is refused there
        median = api_client.put(
            "/api/v1/pricing/target/ozon/btn1",
            json={"target_price": 720, "no_discount_fallback": "account_median"},
        )
        assert median.status_code == 422, median.text
    finally:
        client.command("TRUNCATE TABLE sys_marketplace_actions")
        client.close()
