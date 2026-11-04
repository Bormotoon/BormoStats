from __future__ import annotations

import time

import pytest

from common.article_economics import ArticleEconomicsEngine


def test_multi_account_sku_isolation_and_scoped_tax() -> None:
    """Fixes Copilot #8 and #10: two accounts with the same SKU keep distinct COGS and tax."""
    engine = ArticleEconomicsEngine()
    engine.register_card(
        account_id="acc-taxed",
        marketplace="ozon",
        sku="100500",
        offer_id="ART-1",
        cost_price_rub=100.0,
    )
    engine.register_card(
        account_id="acc-untaxed",
        marketplace="ozon",
        sku="100500",
        offer_id="ART-1",
        cost_price_rub=300.0,
    )

    engine.process_accrual_operation(
        account_id="acc-taxed",
        marketplace="ozon",
        total_operation_amount=900.0,
        line_items=[
            {
                "sku": "100500",
                "sales_qty": 1,
                "sales_rub": 1000.0,
                "commission_rub": -100.0,
            }
        ],
    )
    engine.process_accrual_operation(
        account_id="acc-untaxed",
        marketplace="ozon",
        total_operation_amount=900.0,
        line_items=[
            {
                "sku": "100500",
                "sales_qty": 1,
                "sales_rub": 1000.0,
                "commission_rub": -100.0,
            }
        ],
    )

    report = engine.finalize(
        tax_by_account={"acc-taxed": 60.0},
        tax_status="estimated",
        tax_enabled=True,
    )
    by_acc = {r.account_id: r for r in report.items}

    assert by_acc["acc-taxed"].cogs_rub == 100.0
    assert by_acc["acc-untaxed"].cogs_rub == 300.0
    assert by_acc["acc-taxed"].allocated_tax_rub == 60.0
    assert by_acc["acc-untaxed"].allocated_tax_rub == 0.0
    assert report.total_cogs_rub == 400.0
    assert report.tax_status == "estimated"


def test_linear_o_n_plus_s_performance_under_50k_operations() -> None:
    """Fixes Copilot #18: 50,000 operations across 500 SKUs must complete in < 0.5s."""
    engine = ArticleEconomicsEngine()
    for i in range(500):
        engine.register_card(
            account_id="default",
            marketplace="ozon",
            sku=str(1000 + i),
            offer_id=f"OFFER-{i}",
            cost_price_rub=50.0,
        )

    started = time.perf_counter()
    for n in range(50_000):
        sku = str(1000 + (n % 500))
        engine.process_accrual_operation(
            account_id="default",
            marketplace="ozon",
            total_operation_amount=175.0,
            line_items=[
                {
                    "sku": sku,
                    "sales_qty": 1,
                    "sales_rub": 200.0,
                    "commission_rub": -20.0,
                }
            ],
        )
    report = engine.finalize()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"Engine took {elapsed:.2f}s (expected O(N + S) < 0.5s)"
    assert len(report.items) == 500
    assert report.total_net_accrued_rub == pytest.approx(50_000 * 175.0)
