from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.services.pricing_service import (
    PricingService,
    _breakdown_row,
    _compare_row,
    parse_article_table,
)


def test_cost_table_accepts_spreadsheet_pastes() -> None:
    text = "\n".join(
        [
            "Артикул;Себестоимость",
            "btn30pgf05BK9b;120,50",
            "btn204pgf10gorc\t1 250 ₽",
            "",
            "btn12,99.9",
            "btn30pgf05BK9b;130",
        ]
    )
    costs, errors = parse_article_table(text, "себестоимость")
    assert costs == {"btn30pgf05BK9b": 130.0, "btn204pgf10gorc": 1250.0, "btn12": 99.9}
    assert errors == []


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("a;b\nbtn1;abc", "строка 2: цена — не число"),
        ("btn1;-5", "строка 1: цена должна быть больше нуля"),
        ("btn1 120", "строка 1: нет второго столбца"),
        (";120", "строка 1: неверный артикул"),
    ],
)
def test_cost_table_reports_bad_lines(line: str, error: str) -> None:
    costs, errors = parse_article_table(line, "цена")
    assert costs == {} and errors == [error]


def test_cost_import_of_a_filled_template_lists_the_articles() -> None:
    ch = MagicMock()
    text = "\n".join(["Артикул продавца;Себестоимость", "btn2\t95", "btn1\t120,5", "btn3\t"])
    result = PricingService(ch, "org").import_costs(text)
    assert (result.imported, result.errors, result.updated) == (2, [], ["btn1", "btn2"])
    rows = ch.insert.call_args.args[1]
    assert [(r[1], r[2]) for r in rows] == [("btn2", 95.0), ("btn1", 120.5)]


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "marketplace": "wb",
        "account_id": "default",
        "offer_id": "btn1",
        "product_id": "1001",
        "list_price": 1000.0,
        "seller_discount_pct": 50.0,
        "seller_price": 500.0,
        "mp_discount_pct": 20.0,
        "mp_discount_scope": "product",
        "mp_discount_samples": 5,
        "buyer_price": 400.0,
        "commission_pct": 30.0,
        "commission_rub": 150.0,
        "acquiring_rub": 0.0,
        "logistics_rub": 70.0,
        "fees_rub": 220.0,
        "cost_price": None,
        "margin_rub": None,
        "margin_pct": None,
        "breakeven_price": None,
        "min_price": None,
        "auto_actions_enabled": None,
        "price_seen_at": None,
        "rule_id": None,
        "mode": None,
        "target_price": None,
        "rule_is_active": None,
        "rule_dry_run": None,
    }
    row.update(overrides)
    return row


def test_target_gap_follows_the_rule_mode() -> None:
    assert _breakdown_row(_row()).target_gap_pct is None
    buyer = _breakdown_row(_row(rule_id="r1", mode="buyer_price", target_price=500.0))
    assert buyer.target_gap_pct == -20.0 and buyer.rule_dry_run is False
    seller = _breakdown_row(_row(rule_id="r1", mode="seller_price", target_price=400.0))
    assert seller.target_gap_pct == 25.0
    margin = _breakdown_row(_row(rule_id="r1", mode="margin", target_price=0.0))
    assert margin.target_gap_pct is None


def test_compare_spread_needs_both_marketplaces() -> None:
    both = _compare_row(
        {
            "offer_id": "btn1",
            "wb_seller_price": 500.0,
            "wb_buyer_price": 400.0,
            "ozon_seller_price": 800.0,
            "ozon_buyer_price": 360.0,
            "on_wb": 1,
            "on_ozon": 1,
        }
    )
    assert both.buyer_spread_pct == 11.11
    wb_only = _compare_row(
        {"offer_id": "btn2", "wb_seller_price": 500.0, "wb_buyer_price": 400.0, "on_wb": 1}
    )
    assert wb_only.ozon_buyer_price is None and wb_only.buyer_spread_pct is None
