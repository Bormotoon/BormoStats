from __future__ import annotations

from datetime import UTC, datetime

from collectors.ym.parsers import (
    parse_feedbacks,
    parse_offer_mappings,
    parse_orders,
    parse_prices,
    parse_stocks,
)


def test_parse_orders_maps_marketplace_price_components() -> None:
    rows = parse_orders(
        [
            {
                "id": 42,
                "status": "DELIVERED",
                "creationDate": "2026-10-31T10:00:00Z",
                "items": [
                    {
                        "offerId": "seller-1",
                        "marketSku": 123,
                        "count": 2,
                        "prices": [
                            {"type": "BUYER", "costPerItem": 90},
                            {"type": "SUBSIDY", "costPerItem": 10},
                            {"type": "SELLER", "costPerItem": 100},
                        ],
                    }
                ],
            }
        ],
        "run",
        "business",
    )
    assert rows[0]["order_id"] == 42
    assert rows[0]["offer_id"] == "seller-1"
    assert rows[0]["product_id"] == 123
    assert rows[0]["qty"] == 2
    assert rows[0]["buyer_price"] == 90
    assert rows[0]["seller_price"] == 100
    assert rows[0]["subsidy"] == 10


def test_product_fallback_id_is_deterministic() -> None:
    first = parse_orders([{"id": 1, "items": [{"offerId": "seller-x", "count": 1}]}], "a", "b")
    second = parse_orders([{"id": 1, "items": [{"offerId": "seller-x", "count": 1}]}], "b", "b")
    assert first[0]["product_id"] == second[0]["product_id"]


def test_parse_stocks_and_prices_use_snapshot_fields() -> None:
    timestamp = datetime(2026, 11, 1, tzinfo=UTC)
    stocks = parse_stocks(
        [
            {
                "offerId": "sku",
                "marketSku": 7,
                "stocks": [{"warehouse": {"id": 4, "name": "Main"}, "fit": 8, "freeze": 2}],
            }
        ],
        "run",
        "business",
        timestamp,
    )
    assert stocks[0]["warehouse_name"] == "Main"
    assert stocks[0]["stock_fit"] == 8
    prices = parse_prices(
        [{"offerId": "sku", "marketSku": 7, "price": {"value": 80, "discountBase": 100}}],
        "run",
        "business",
        timestamp,
    )
    assert prices[0]["seller_price"] == 80
    assert prices[0]["list_price"] == 100


def test_parse_offer_mappings_and_feedback() -> None:
    mappings = parse_offer_mappings(
        [
            {
                "mapping": {
                    "offer": {"offerId": "sku", "purchasePrice": {"value": 50}},
                    "market": {"id": 19, "name": "Product", "pictures": ["https://img"]},
                }
            }
        ],
        "run",
        "business",
    )
    assert mappings[0]["market_sku"] == 19
    assert mappings[0]["purchase_price"] == 50
    feedback = parse_feedbacks(
        [
            {
                "feedbackId": 10,
                "marketSku": 19,
                "statistics": {"rating": 5},
                "description": {"comment": "Good", "advantages": "Fast"},
                "needReaction": False,
            }
        ],
        "run",
        "business",
    )
    assert feedback[0]["review_id"] == "10"
    assert feedback[0]["is_answered"] is True


def test_business_order_prices_are_totals_not_unit_prices() -> None:
    rows = parse_orders(
        [
            {
                "orderId": 10,
                "items": [
                    {
                        "offerId": "s",
                        "count": 2,
                        "prices": {
                            "payment": {"value": 180},
                            "cashback": {"value": 10},
                            "subsidy": {"value": 10},
                        },
                    }
                ],
            }
        ],
        "r",
        "a",
    )
    assert rows[0]["buyer_price"] == 90
    assert rows[0]["seller_price"] == 100
    assert rows[0]["subsidy"] == 5


def test_catalog_and_warehouse_shapes_from_openapi() -> None:
    rows = parse_offer_mappings(
        [
            {
                "offer": {"offerId": "s", "name": "Name", "pictures": ["img"]},
                "mapping": {"marketSku": 123},
            }
        ],
        "r",
        "a",
    )
    assert rows[0]["offer_id"] == "s"
    assert rows[0]["market_sku"] == 123
    assert rows[0]["product_id"] == 123
    assert rows[0]["pictures"] == ["img"]
    stocks = parse_stocks(
        [
            {
                "warehouseId": 7,
                "offers": [
                    {
                        "offerId": "s",
                        "stocks": [{"type": "FIT", "count": 0}, {"type": "FREEZE", "count": 2}],
                    }
                ],
            }
        ],
        "r",
        "a",
        datetime.now(UTC),
    )
    assert len(stocks) == 1
    assert stocks[0]["stock_fit"] == 0
    assert stocks[0]["stock_freeze"] == 2
    assert stocks[0]["warehouse_id"] == 7


def test_finance_preserves_category_and_distinct_transaction_ids() -> None:
    from collectors.ym.parsers import parse_united_netting
    from common.finance import classify_ym_finance

    records = [
        {"date": "2026-11-01", "serviceType": "reverse_logistics", "amount": -10},
        {"date": "2026-11-01", "serviceType": "storage", "amount": -20},
    ]
    rows = parse_united_netting(records, "r", "a")
    assert rows[0]["transaction_id"] != rows[1]["transaction_id"]
    assert classify_ym_finance("return", rows[0]["service_type"]) == "reverse_logistics"
    assert classify_ym_finance("charge", "FEE") == "commission"
    assert classify_ym_finance("payout", "") == "payouts"


def test_official_csv_headers_and_report_amounts() -> None:
    from collectors.ym.parsers import parse_shows_boost, parse_shows_sales, parse_united_netting

    finance = parse_united_netting(
        [
            {
                "TRANSACTION_DATE": "02.11.2026",
                "TRANSACTION_ID": "t",
                "SHOP_SKU": "s",
                "TRANSACTION_SUM": "-1 200,50",
                "TRANSACTION_TYPE": "charge",
                "OFFER_OR_SERVICE_NAME": "storage",
            }
        ],
        "r",
        "a",
    )[0]
    assert finance["amount"] == -1200.5
    assert finance["offer_id"] == "s"
    assert finance["service_type"] == "storage"
    funnel = parse_shows_sales(
        [
            {
                "DAY": "2026-11-02",
                "OFFER_ID": "s",
                "ORDER_ITEMS": "3",
                "ORDER_ITEMS_TOTAL_AMOUNT": "1200",
                "SHOWS": "20",
            }
        ],
        "r",
        "a",
    )[0]
    assert (funnel["orders"], funnel["revenue"]) == (3, 1200)
    ads = parse_shows_boost(
        [
            {
                "DATE": "2026-11-02",
                "SALE_CAMPAIGN_ID": "7",
                "REAL_COST": "10",
                "ORDERED_COUNT": "2",
                "ORDERED_AMOUNT": "100",
            }
        ],
        "r",
        "a",
    )[0]
    assert (ads["_campaignId"], ads["amount"], ads["orders"]) == ("7", 10, 2)


def test_payment_report_uses_transaction_source_for_sales_and_returns() -> None:
    from collectors.ym.parsers import parse_united_netting
    from common.finance import classify_ym_finance

    rows = parse_united_netting(
        [
            {
                "TRANSACTION_DATE": "2026-11-02",
                "TRANSACTION_SOURCE": "Платеж покупателя",
                "TRANSACTION_TYPE": "Начисление",
                "OFFER_OR_SERVICE_NAME": "Книга",
                "TRANSACTION_SUM": "100",
            },
            {
                "TRANSACTION_DATE": "2026-11-02",
                "TRANSACTION_SOURCE": "Возврат платежа покупателя",
                "TRANSACTION_TYPE": "Возврат",
                "OFFER_OR_SERVICE_NAME": "Книга",
                "TRANSACTION_SUM": "-100",
            },
        ],
        "r",
        "a",
    )
    assert [classify_ym_finance(r["transaction_type"], r["service_type"]) for r in rows] == [
        "sales",
        "returns",
    ]


def test_statistics_retains_buyer_prices_and_only_attributable_order_commissions() -> None:
    from collectors.ym.parsers import parse_order_statistics

    order = {
        "id": 101,
        "status": "DELIVERED",
        "creationDate": "2026-11-01",
        "commissions": [{"type": "FEE", "actual": 120}, {"type": "AGENCY", "actual": 10}],
        "items": [
            {
                "shopSku": "one",
                "marketSku": 44,
                "count": 2,
                "prices": [
                    {"type": "BUYER", "costPerItem": 800},
                    {"type": "CASHBACK", "costPerItem": 100},
                ],
            }
        ],
    }
    one = parse_order_statistics([order], "run", "account")[0]
    assert (one["buyer_price"], one["cashback"], one["fee"], one["acquiring"]) == (
        800,
        100,
        120,
        10,
    )
    order["items"].append({"shopSku": "two", "count": 1})
    multiple = parse_order_statistics([order], "run", "account")
    assert all(row["fee"] is None and row["acquiring"] is None for row in multiple)
    assert multiple[1]["buyer_price"] is None


def test_tariffs_do_not_sum_alternative_prices_for_same_service() -> None:
    from collectors.ym.parsers import parse_tariff_quotes

    row = parse_tariff_quotes(
        [
            {
                "_offerId": "sku",
                "_price": 1000,
                "tariffs": [
                    {"type": "FEE", "amount": 80},
                    {"type": "SORTING", "amount": 5},
                    {"type": "SORTING", "amount": 10},
                    {"type": "AGENCY_COMMISSION", "amount": 20},
                ],
            }
        ],
        "run",
        "account",
    )[0]
    assert row["fee"] == 80
    assert row["acquiring"] == 20
    assert row["logistics"] is None


def test_statistics_preserves_fully_removed_item_details_without_fabricating_price() -> None:
    from collectors.ym.parsers import parse_order_statistics

    rows = parse_order_statistics(
        [
            {
                "id": 44,
                "status": "RETURNED",
                "creationDate": "2026-11-01",
                "items": [],
                "commissions": [],
                "initialItems": [
                    {
                        "shopSku": "x",
                        "count": 0,
                        "initialCount": 2,
                        "details": [
                            {"itemStatus": "RETURNED", "itemCount": 2, "updateDate": "2026-11-02"}
                        ],
                    }
                ],
            }
        ],
        "r",
        "a",
    )
    assert len(rows) == 1 and rows[0]["offer_id"] == "x"
    assert rows[0]["buyer_price"] is None
    assert "RETURNED" in rows[0]["payload"]


def test_statistics_interprets_naive_time_in_moscow() -> None:
    from collectors.ym.parsers import parse_order_statistics

    row = parse_order_statistics(
        [
            {
                "id": 1,
                "creationDate": "2026-11-01",
                "statusUpdateDate": "2026-11-01T12:00:00",
                "items": [{"shopSku": "s", "count": 1}],
            }
        ],
        "r",
        "a",
    )[0]
    assert row["updated_at"] == datetime(2026, 11, 1, 9)
