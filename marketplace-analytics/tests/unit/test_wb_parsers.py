from __future__ import annotations

from datetime import date

from collectors.wb.parsers import parse_funnel, parse_orders, parse_sales


def test_parse_sales_marks_return_rows() -> None:
    records = [
        {
            "srid": "sale-1",
            "lastChangeDate": "2026-03-01T12:00:00+03:00",
            "date": "2026-03-01T10:00:00+03:00",
            "nmId": 111,
            "chrtId": 222,
            "quantity": -1,
            "totalPrice": 100.0,
            "ppvzForPay": 85.0,
            "supplierOperName": "Возврат",
        }
    ]

    rows = parse_sales(records, run_id="run-1", account_id="acc-1")
    assert len(rows) == 1
    row = rows[0]
    assert row["srid"] == "sale-1"
    assert row["is_return"] == 1
    assert row["quantity"] == 1
    assert row["nm_id"] == 111
    assert row["chrt_id"] == 222


def test_parse_orders_supports_alias_fields() -> None:
    records = [
        {
            "odid": "order-1",
            "lastChangeDt": "2026-03-01T12:00:00+03:00",
            "date": "2026-03-01T10:00:00+03:00",
            "nmId": 111,
            "chrtId": 222,
            "quantity": 3,
            "priceWithDisc": 149.5,
        }
    ]

    rows = parse_orders(records, run_id="run-1", account_id="acc-1")

    assert len(rows) == 1
    row = rows[0]
    assert row["srid"] == "order-1"
    assert row["quantity"] == 3
    assert row["price_rub"] == 149.5


def test_parse_funnel_supports_alias_metrics_fields() -> None:
    records = [
        {
            "day": "2026-03-01T00:00:00Z",
            "nm_id": 111,
            "views": 120,
            "addsToCart": 14,
            "orders": 5,
            "ordersRevenue": 700.0,
            "buyouts": 4,
            "cancels": 1,
            "addToCartCR": 0.12,
            "cartToOrderCR": 0.41,
            "buyoutCR": 0.8,
            "wishlist": 9,
        }
    ]

    rows = parse_funnel(records, run_id="run-1", account_id="acc-1")

    assert len(rows) == 1
    row = rows[0]
    assert row["day"] == date(2026, 3, 1)
    assert row["open_card_count"] == 120
    assert row["add_to_cart_count"] == 14
    assert row["orders_sum_rub"] == 700.0
    assert row["buyout_percent"] == 0.8
