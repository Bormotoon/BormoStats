from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from collectors.ozon.parsers import (
    parse_ads_daily,
    parse_finance_accruals,
    parse_postings,
    parse_stocks,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOT = datetime(2026, 3, 1, 12, 0, 0)


def _load_json_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _money(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def test_parse_postings_maps_v4_fbs_posting() -> None:
    posting_rows, item_rows = parse_postings(
        [_load_json_fixture("ozon_fbs_posting_v4.json")],
        run_id="run-1",
        account_id="acc-1",
    )

    assert len(posting_rows) == 1
    posting = posting_rows[0]
    assert posting["posting_number"] == "POST-1"
    assert posting["status"] == "cancelled"
    assert posting["created_at"] == datetime(2026, 3, 1, 10, 0, 0)
    assert posting["shipped_at"] == datetime(2026, 3, 3, 12, 0, 0)
    assert posting["ozon_warehouse_id"] == 123
    # the list methods expose no delivery/cancellation timestamps
    assert posting["delivered_at"] is None
    assert posting["canceled_at"] is None

    assert [(row["ozon_product_id"], row["quantity"]) for row in item_rows] == [
        (100500, 2),
        (100600, 1),
    ]
    # price is a money object; payout comes from financial_data matched by SKU
    assert item_rows[0]["price"] == 1499.0
    assert item_rows[0]["payout"] == 1299.0
    assert item_rows[1]["price"] == 500.0
    assert item_rows[1]["payout"] == 500.0


def test_parse_postings_takes_fbo_warehouse_from_analytics_data() -> None:
    posting = {
        "posting_number": "FBO-1",
        "status": "delivered",
        "created_at": "2026-03-01T10:00:00Z",
        "analytics_data": {"warehouse_id": 555, "warehouse_name": "Хоругвино"},
        "products": [{"sku": 1, "quantity": 1, "price": _money("10")}],
    }

    posting_rows, _ = parse_postings([posting], run_id="run-1", account_id="acc-1")

    assert posting_rows[0]["ozon_warehouse_id"] == 555


def test_parse_stocks_maps_v4_items_per_sku_and_warehouse() -> None:
    rows = parse_stocks(
        [
            {
                "product_id": 7001,
                "offer_id": "offer-1",
                "stocks": [
                    {
                        "sku": 100500,
                        "type": "fbs",
                        "warehouse_ids": [12],
                        "present": 9,
                        "reserved": 2,
                    },
                    {"sku": 100500, "type": "rfbs", "warehouse_ids": [], "present": 3},
                    {"sku": 100500, "type": "fbp", "warehouse_ids": [], "present": 1},
                ],
            }
        ],
        run_id="run-1",
        account_id="acc-1",
        snapshot_ts=SNAPSHOT,
    )

    by_warehouse = {row["warehouse_id"]: row for row in rows}
    assert set(by_warehouse) == {12, None}
    assert by_warehouse[12]["ozon_product_id"] == 100500
    assert (by_warehouse[12]["present"], by_warehouse[12]["reserved"]) == (9, 2)
    # stocks without a single warehouse share the dedup key, so they are summed
    assert (by_warehouse[None]["present"], by_warehouse[None]["reserved"]) == (4, 0)


def test_parse_stocks_prefers_fbo_analytics_rows_over_v4_fbo_totals() -> None:
    rows = parse_stocks(
        [
            {
                "product_id": 7001,
                "offer_id": "offer-1",
                "stocks": [{"sku": 100500, "type": "fbo", "warehouse_ids": [], "present": 50}],
            },
            {
                "sku": 100500,
                "offer_id": "offer-1",
                "warehouse_id": 900,
                "warehouse_name": "Хоругвино",
                "available_stock_count": 30,
                "transit_stock_count": 5,
            },
            {
                "sku": 100500,
                "offer_id": "offer-1",
                "warehouse_id": 901,
                "available_stock_count": 15,
            },
        ],
        run_id="run-1",
        account_id="acc-1",
        snapshot_ts=SNAPSHOT,
    )

    assert sorted((row["warehouse_id"], row["present"]) for row in rows) == [(900, 30), (901, 15)]


def test_parse_ads_daily_maps_performance_rows() -> None:
    rows = parse_ads_daily(
        [
            {
                "id": "123",
                "title": "Кампания",
                "date": "2026-03-01",
                "views": "1 000",
                "clicks": "50",
                "moneySpent": "1 234,56",
                "avgBid": "10,00",
                "orders": "3",
                "ordersMoney": "4500,5",
            },
            {"id": "124", "date": "02.03.2026", "views": 7, "moneySpent": 1.5},
            {"id": "125", "date": ""},
        ],
        run_id="run-1",
        account_id="acc-1",
    )

    assert len(rows) == 2
    first = rows[0]
    assert first["day"] == date(2026, 3, 1)
    assert first["campaign_id"] == "123"
    assert (first["impressions"], first["clicks"], first["orders"]) == (1000, 50, 3)
    assert first["cost"] == 1234.56
    assert first["revenue"] == 4500.5
    assert rows[1]["day"] == date(2026, 3, 2)
    assert rows[1]["cost"] == 1.5


def test_parse_finance_accruals_maps_every_category() -> None:
    records = [
        {
            "accrual_id": 1001,
            "date": "2026-09-15",
            "accrued_category": "POSTING",
            "unit_number": "POST-1",
            "posting": {
                "delivery_schema": "FBO",
                "products": [
                    {
                        "sku": 100500,
                        "commission": {
                            "seller_price": _money("1000"),
                            "sale_commission": _money("-150"),
                        },
                        "delivery": {
                            "services": [{"type_id": 32, "accrued": _money("-80")}],
                            "total_accrued": _money("-80"),
                        },
                    }
                ],
            },
            "total_amount": _money("770.00"),
        },
        {
            "accrual_id": 1002,
            "date": "2026-09-15",
            "accrued_category": "NON_ITEM",
            "unit_number": "ad-contract-7",
            "non_item_fee": {"type_id": 41, "accrued": _money("-300")},
            "total_amount": _money("-300"),
        },
        {
            "accrual_id": 1003,
            "date": "2026-09-15",
            "accrued_category": "ITEM",
            "item_fees": {
                "fees": [
                    {"sku": 1, "fees": [{"type_id": 1, "accrued": _money("-5")}]},
                    {"sku": 2, "fees": [{"type_id": 1, "accrued": _money("-7")}]},
                ]
            },
            "total_amount": _money("-12"),
        },
        {
            "accrual_id": 1004,
            "date": "2026-09-15",
            "accrued_category": "CONTAINER_FEES",
            "container_fees": {
                "fees": [
                    {"type_id": 77, "accrued": _money("-20")},
                    {"type_id": 78, "accrued": _money("-5")},
                ]
            },
            "total_amount": {"amount": "-25", "currency": "CNY"},
        },
        {
            "accrual_id": 1005,
            "date": "2026-09-15",
            "accrued_category": "NON_ITEM",
            "non_item_fee": {"type_id": 999, "accrued": _money("-1")},
            "total_amount": _money("-1"),
        },
        # accruals without an id or a date cannot be stored idempotently
        {"date": "2026-09-15", "total_amount": _money("-1")},
        {"accrual_id": 1006, "total_amount": _money("-1")},
    ]

    rows = parse_finance_accruals(
        records,
        run_id="run-1",
        account_id="acc-1",
        type_names={1: "Acquiring", 41: "PayPerClick"},
    )

    assert [(r["operation_id"], r["type"], r["amount"], r["currency"]) for r in rows] == [
        ("1001", "posting", 770.0, "RUB"),
        ("1002", "PayPerClick", -300.0, "RUB"),
        ("1003", "Acquiring", -12.0, "RUB"),
        ("1004", "container_fees", -25.0, "CNY"),
        ("1005", "accrual_type_999", -1.0, "RUB"),
    ]
    assert all(r["operation_ts"] == datetime(2026, 9, 15) for r in rows)
    assert all(r["source"] == "accrual_by_day" for r in rows)
    assert json.loads(rows[0]["payload"])["unit_number"] == "POST-1"
