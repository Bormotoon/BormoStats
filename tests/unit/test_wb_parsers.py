from __future__ import annotations

from datetime import date, datetime

from collectors.wb.parsers import parse_funnel, parse_orders, parse_sales, parse_stocks


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


def _v3_funnel_record(nm_id: int, day: str) -> dict[str, object]:
    return {
        "product": {"nmId": nm_id, "vendorCode": "vc-1"},
        "statistic": {
            "selected": {
                "period": {"start": day, "end": day},
                "openCount": 14,
                "cartCount": 6,
                "orderCount": 3,
                "orderSum": 1800,
                "buyoutCount": 2,
                "buyoutSum": 1200,
                "cancelCount": 1,
                "cancelSum": 600,
                "addToWishlist": 1,
                "conversions": {
                    "addToCartPercent": 43,
                    "cartToOrderPercent": 50,
                    "buyoutPercent": 67,
                },
            },
            "past": {"period": {"start": "2000-01-01", "end": "2000-01-01"}, "openCount": 99},
        },
        "currency": "RUB",
    }


def test_parse_funnel_supports_v3_sales_funnel_records() -> None:
    rows = parse_funnel(
        [_v3_funnel_record(148489618, "2026-09-28")], run_id="run-1", account_id="acc-1"
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["day"] == date(2026, 9, 28)
    assert row["nm_id"] == 148489618
    assert row["open_card_count"] == 14
    assert row["add_to_cart_count"] == 6
    assert row["orders_count"] == 3
    assert row["orders_sum_rub"] == 1800.0
    assert row["buyouts_count"] == 2
    assert row["cancel_sum_rub"] == 600.0
    assert row["add_to_cart_conv"] == 43.0
    assert row["cart_to_order_conv"] == 50.0
    assert row["buyout_percent"] == 67.0
    assert row["add_to_wishlist"] == 1
    assert row["currency"] == "RUB"
    assert "past" not in row["payload"]


def test_parse_stocks_maps_wb_warehouses_report_rows() -> None:
    rows = parse_stocks(
        [
            {
                "nmId": 111,
                "chrtId": 222,
                "warehouseId": -999999,
                "warehouseName": "Склад WB",
                "regionName": "Склад WB",
                "quantity": 7,
                "inWayToClient": 3,
                "inWayFromClient": 1,
            },
            {"nmId": 111, "chrtId": 333, "warehouseId": 507, "quantity": 2},
            {"nmId": 111, "chrtId": 333, "warehouseId": 686, "quantity": 5},
        ],
        run_id="run-1",
        account_id="acc-1",
        snapshot_ts=datetime(2026, 9, 29, 12, 0, 0),
    )

    by_chrt = {row["chrt_id"]: row for row in rows}
    assert set(by_chrt) == {222, 333}
    # the aggregated "Склад WB" id is negative and not a real warehouse
    assert by_chrt[222]["warehouse_id"] is None
    assert by_chrt[222]["amount"] == 7
    assert by_chrt[222]["nm_id"] == 111
    # one row per size: warehouses are summed and the warehouse becomes ambiguous
    assert by_chrt[333]["amount"] == 7
    assert by_chrt[333]["warehouse_id"] is None
