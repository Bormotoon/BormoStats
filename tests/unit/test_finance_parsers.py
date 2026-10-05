from __future__ import annotations

from datetime import date

import pytest

from collectors.ozon.parsers import parse_finance_balance
from collectors.wb.parsers import parse_sales_report_lines
from common.finance import FINANCE_CATEGORIES


def _money(value: float) -> dict[str, object]:
    return {"value": value, "currency_code": "RUB"}


def test_ozon_balance_categories_add_up_to_the_accrual() -> None:
    payload = {
        "total": {
            "opening_balance": _money(30440.76),
            "closing_balance": _money(47590.23),
            "accrued": _money(44869.62),
            "payments": [_money(-27720.15)],
        },
        "cashflows": {
            "sales": {"amount": _money(227353), "fee": _money(-112916.16)},
            "returns": {"amount": _money(-7020), "fee": _money(3344.2)},
            "services": [
                {"name": "logistics", "amount": _money(-38947.28)},
                {"name": "reverse_logistics", "amount": _money(-8421.28)},
                {"name": "courier_client_reinvoice", "amount": _money(-4464.87)},
                {"name": "partner_returns_cancellations_processing", "amount": _money(-1410)},
                {"name": "delivery_to_handover_place_by_ozon", "amount": _money(-675)},
                {"name": "acquiring", "amount": _money(-1722.92)},
                {"name": "product_placement_in_ozon_warehouses", "amount": _money(-9425.07)},
                {"name": "packing_by_agents", "amount": _money(-550)},
                {"name": "packing_package", "amount": _money(-275)},
            ],
        },
    }

    row = parse_finance_balance(payload, day=date(2026, 9, 30), run_id="r", account_id="a")

    # September 2026 of the real account: the balance of the seller cabinet
    assert sum(row[c] for c in FINANCE_CATEGORIES) == pytest.approx(44869.62)
    assert row["net_accrued"] == 44869.62
    assert row["commission"] == pytest.approx(-109571.96)
    assert row["storage"] == -9425.07
    assert row["other"] == -825.0  # the packing services, kept by name
    assert row["services"]["packing_by_agents"] == -550.0
    assert row["payouts"] == -27720.15
    assert row["opening_balance"] + row["net_accrued"] + row["payouts"] == pytest.approx(
        row["closing_balance"]
    )


def test_ozon_balance_puts_an_unexplained_difference_into_other() -> None:
    payload = {
        "total": {"accrued": _money(10.0), "payments": []},
        "cashflows": {"sales": {"amount": _money(100.0), "fee": _money(-50.0)}},
    }

    row = parse_finance_balance(payload, day=date(2026, 9, 1), run_id="r", account_id="a")

    assert row["other"] == -40.0
    assert row["services"]["unexplained"] == -40.0
    assert sum(row[c] for c in FINANCE_CATEGORIES) == pytest.approx(row["net_accrued"])


def test_wb_report_lines_follow_the_payout_formula() -> None:
    def line(rrd_id: int, doc: str, **money: float) -> dict[str, object]:
        return {
            "rrdId": rrd_id,
            "reportId": 1,
            "reportType": 1,
            "rrDate": "2026-09-10",
            "nmId": 5,
            "docTypeName": doc,
            "sellerOperName": doc or "Логистика",
            "quantity": 1 if doc else 0,
            **{key: str(value) for key, value in money.items()},
        }

    rows = parse_sales_report_lines(
        [
            line(1, "Продажа", retailPriceWithDisc=449, forPay=276.13, acquiringFee=12),
            line(2, "Возврат", retailPriceWithDisc=449, forPay=276.13, acquiringFee=12),
            line(3, "", deliveryService=40, paidStorage=3, penalty=2, deduction=-10),
        ],
        run_id="r",
        account_id="a",
    )

    sale, ret, charges = rows
    assert (sale["sales"], sale["acquiring"], sale["net_accrued"]) == (449.0, -12.0, 276.13)
    assert sale["commission"] == pytest.approx(276.13 - 449 + 12)
    assert (ret["returns"], ret["net_accrued"]) == (-449.0, -276.13)
    # deduction -10 is a credit to the seller
    assert (charges["logistics"], charges["storage"], charges["penalties"]) == (-40.0, -3.0, -2.0)
    assert charges["other"] == 10.0
    assert charges["net_accrued"] == pytest.approx(-40 - 3 - 2 + 10)
    for row in rows:
        assert sum(row[c] for c in FINANCE_CATEGORIES) == pytest.approx(row["net_accrued"])
