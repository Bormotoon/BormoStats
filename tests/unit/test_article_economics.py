import json
import unittest
from datetime import date
from decimal import Decimal as D  # noqa: N817

from app.services.article_economics_service import ArticleEconomicsService

from common.article_economics import EXPENSES, AccrualEconomics, metric_row


class ArticleEconomicsTests(unittest.TestCase):
    def test_sale_return_and_shared_fees_reconcile(self):
        e = AccrualEconomics()
        e.add(
            {
                "date": "2026-10-27",
                "total_amount": {"amount": "70"},
                "posting": {
                    "products": [
                        {
                            "sku": 1,
                            "quantity": 1,
                            "commission": {
                                "sale_amount": {"amount": "100"},
                                "sale_price": {"amount": "60"},
                                "commission": {"amount": "-20"},
                            },
                            "delivery": {
                                "total_accrued": {"amount": "-10"},
                                "services": [{"type_id": 32, "accrued": {"amount": "-10"}}],
                            },
                        }
                    ]
                },
            }
        )
        e.add(
            {
                "date": "2026-10-27",
                "total_amount": {"amount": "-40"},
                "posting": {
                    "products": [
                        {
                            "sku": 2,
                            "quantity": 1,
                            "commission": {
                                "sale_amount": {"amount": "-50"},
                                "sale_price": {"amount": "-30"},
                                "commission": {"amount": "10"},
                            },
                        }
                    ]
                },
            }
        )
        e.add(
            {
                "date": "2026-10-27",
                "total_amount": {"amount": "-1.01"},
                "non_item_fee": {"type_id": 41, "accrued": {"amount": "-1.01"}},
            }
        )
        shared = e.allocate()
        self.assertEqual(e.net(), D("28.99"))
        self.assertEqual(e.rows["2"]["buyer_revenue"], D("-30"))
        self.assertEqual(sum(r["marketing"] for r in e.rows.values()), D("1.01"))
        self.assertEqual(shared["marketing"], D("1.01"))
        self.assertEqual(e.rows["1"]["marketing"], D(0))
        self.assertEqual(e.rows["unallocated"]["marketing"], D("1.01"))

    def test_unknown_operations_are_preserved(self):
        e = AccrualEconomics()
        e.add({"total_amount": {"amount": "12.33"}})
        e.allocate()
        self.assertEqual(e.net(), D("12.33"))
        self.assertIn("unallocated", e.rows)

    def test_performance_is_exact_and_keeps_unmatched_cost(self):
        e = AccrualEconomics()
        e.add(
            {
                "date": "2026-10-27",
                "unit_number": "campaign",
                "total_amount": {"amount": "-5"},
                "non_item_fee": {"type_id": 41, "accrued": {"amount": "-5"}},
            }
        )
        e.allocate()
        linked, _ = e.bind_ad_costs(
            [
                ("2026-10-27", "campaign", "sku1", D("2.50")),
                ("2026-10-27", "campaign", "sku2", D("1.50")),
                ("2026-10-27", "other", "sku3", D(99)),
            ]
        )
        self.assertEqual(linked, D(4))
        self.assertEqual(e.rows["sku1"]["marketing"], D("2.50"))
        self.assertEqual(e.rows["unallocated"]["marketing"], D(1))
        self.assertEqual(e.net(), D(-5))

    def test_weighted_totals_and_missing_cost(self):
        v = {
            k: D(0)
            for k in (
                *EXPENSES,
                "sales_qty",
                "returns_qty",
                "revenue",
                "buyer_revenue",
                "commission",
                "external",
                "tax",
            )
        }
        v.update(
            sales_qty=D(3),
            returns_qty=D(-1),
            revenue=D(200),
            commission=D(40),
            cogs=D(80),
            tax=D(10),
        )
        row = metric_row(v)
        self.assertEqual(row["revenue_unit"], D(100))
        self.assertEqual(row["operating"], D(80))
        self.assertEqual(row["profit"], D(70))
        self.assertEqual(row["roi"], D(".875"))
        self.assertEqual(row["profit_pct"], D(".35"))
        v["cogs"] = None
        row = metric_row(v)
        self.assertIsNone(row["profit"])
        self.assertIsNone(row["cogs_unit"])

    def test_accrual_economics_wb_realization_row(self):
        e = AccrualEconomics()
        e.add_wb_realization_row(
            {
                "nm_id": 123456,
                "quantity": 2,
                "retail_price_withdisc_rub": 500,
                "retail_amount": 550,
                "ppvz_for_pay": 850,
                "acquiring_fee": 15,
                "delivery_rub": 50,
                "storage_fee": 10,
                "penalty": 5,
                "doc_type_name": "Продажа",
                "supplier_oper_name": "Продажа",
            }
        )
        self.assertEqual(e.raw_total, D("770"))
        self.assertEqual(e.net(), D("770"))
        row = e.rows["123456"]
        self.assertEqual(row["sales_qty"], D(2))
        self.assertEqual(row["revenue"], D(1000))
        self.assertEqual(row["commission"], D(150))
        self.assertEqual(row["acquiring"], D(15))
        self.assertEqual(row["logistics"], D(50))
        self.assertEqual(row["storage"], D(10))
        self.assertEqual(row["other_services"], D(5))

    def test_accrual_economics_standardized_sale(self):
        e = AccrualEconomics()
        e.add_standardized_sale(
            sku="SKU-YM-1",
            qty=D(3),
            revenue=D(1500),
            buyer_revenue=D(1400),
            commission=D(150),
            acquiring=D(30),
            logistics=D(120),
        )
        self.assertEqual(e.raw_total, D(1200))
        self.assertEqual(e.net(), D(1200))
        row = e.rows["SKU-YM-1"]
        self.assertEqual(row["sales_qty"], D(3))
        self.assertEqual(row["revenue"], D(1500))
        self.assertEqual(row["buyer_revenue"], D(1400))
        self.assertEqual(row["commission"], D(150))
        self.assertEqual(row["acquiring"], D(30))
        self.assertEqual(row["logistics"], D(120))

    def test_article_economics_wb_realization_and_fallback(self):
        class MockResult:
            def __init__(self, rows=(), result_rows=()):
                self._rows = rows
                self.result_rows = result_rows or rows

            def named_results(self):
                return iter(self._rows)

        class MockCH:
            def query(self, sql, **kwargs):
                if "FROM dim_account" in sql:
                    return MockResult(result_rows=[("wb", "default")])
                if "FROM dim_product" in sql:
                    return MockResult(
                        [
                            {
                                "marketplace": "wb",
                                "account_id": "default",
                                "product_id": 12345,
                                "offer_id": "WB-ITEM-1",
                                "title": "WB Product 1",
                                "image_url": "https://img/wb1.jpg",
                            }
                        ]
                    )
                if "FROM v_offer_cost" in sql:
                    return MockResult(result_rows=[("wb", "default", "WB-ITEM-1", 100.0)])
                if "FROM dim_offer_cost" in sql or "FROM dim_product_cost" in sql:
                    return MockResult(result_rows=[])
                if "FROM raw_wb_finance_report" in sql:
                    payload = {
                        "nm_id": 12345,
                        "quantity": 2,
                        "retail_price_withdisc_rub": 500,
                        "retail_amount": 550,
                        "ppvz_for_pay": 850,
                        "acquiring_fee": 15,
                        "delivery_rub": 50,
                        "storage_fee": 10,
                        "penalty": 5,
                        "doc_type_name": "Продажа",
                        "supplier_oper_name": "Продажа",
                    }
                    return MockResult(
                        [
                            {
                                "day": date(2026, 9, 1),
                                "account_id": "default",
                                "payload": json.dumps(payload),
                            }
                        ]
                    )
                if "FROM stg_sales" in sql:
                    return MockResult(
                        [
                            {
                                "day": date(2026, 9, 15),
                                "account_id": "default",
                                "product_id": 12345,
                                "qty": 1,
                                "sales_rub": 600,
                                "commission_pct": 10,
                                "acquiring_rub": 10,
                                "logistics_rub": 30,
                            }
                        ]
                    )
                if "FROM mrt_finance_daily" in sql:
                    # Report gave 770 + fallback gave 600 - 60 - 10 - 30 = 500 -> total 1270.
                    # Suppose mrt_finance_daily says 1300 -> 30 unallocated delta!
                    return MockResult([{"total_net_accrued": 1300.0}])
                if "FROM mrt_ad_performance_daily" in sql:
                    return MockResult([{"sku": "12345", "cost": 25.0}])
                if "FROM mrt_ads_daily" in sql:
                    return MockResult([{"total_cost": 40.0}])
                if "FROM dim_additional_expense" in sql:
                    return MockResult(result_rows=[])
                raise AssertionError(f"Unexpected query: {sql}")

        svc = ArticleEconomicsService(MockCH(), "default")
        res = svc.build(date(2026, 9, 1), date(2026, 9, 30), marketplace="wb")
        items = res["items"]
        self.assertTrue(len(items) >= 2)  # SKU row + unallocated row
        sku_row = next(r for r in items if r["sku"] == "12345")
        unallocated_row = next(r for r in items if r["sku"] == "unallocated")
        self.assertEqual(unallocated_row["marketplace"], "wb")

        self.assertEqual(sku_row["marketplace"], "wb")
        self.assertEqual(sku_row["offer_id"], "WB-ITEM-1")
        # Sales: 2 from report (1000) + 1 from fallback (600) = 1600 revenue
        self.assertEqual(sku_row["sales_qty"], 3)
        self.assertEqual(sku_row["revenue"], 1600.0)
        # Cost price: 100 * 3 units = 300
        self.assertEqual(sku_row["cogs"], 300.0)
        self.assertEqual(sku_row["marketing"], 25.0)

        # Unallocated delta reconciliation: total net accrued across items must match 1300.0
        total_net = sum(r["net_accrued"] for r in items)
        self.assertAlmostEqual(total_net, 1300.0, places=2)
        self.assertAlmostEqual(res["total"]["net_accrued"], 1300.0, places=2)

    def test_article_economics_ym_reconciliation(self):
        class MockResult:
            def __init__(self, rows=(), result_rows=()):
                self._rows = rows
                self.result_rows = result_rows or rows

            def named_results(self):
                return iter(self._rows)

        class MockYMCH:
            def query(self, sql, **kwargs):
                if "FROM dim_account" in sql:
                    return MockResult(result_rows=[("ym", "default")])
                if "FROM dim_product" in sql:
                    return MockResult(
                        [
                            {
                                "marketplace": "ym",
                                "account_id": "default",
                                "product_id": "YM-001",
                                "offer_id": "YM-OFFER-1",
                                "title": "YM Product 1",
                                "image_url": None,
                            }
                        ]
                    )
                if "FROM v_offer_cost" in sql:
                    return MockResult(result_rows=[("ym", "default", "YM-OFFER-1", 200.0)])
                if "FROM dim_offer_cost" in sql or "FROM dim_product_cost" in sql:
                    return MockResult(result_rows=[])
                if "FROM stg_sales" in sql:
                    return MockResult(
                        [
                            {
                                "day": date(2026, 9, 5),
                                "account_id": "default",
                                "product_id": "YM-001",
                                "qty": 4,
                                "sales_rub": 2000,
                                "commission_pct": 12,
                                "acquiring_rub": 20,
                                "logistics_rub": 100,
                            }
                        ]
                    )
                if "FROM mrt_finance_daily" in sql:
                    # 2000 - 240 (comm) - 20 (acq) - 100 (log) = 1640.
                    # mrt_finance_daily says 1500 (e.g. storage deduction of 140)
                    return MockResult([{"total_net_accrued": 1500.0}])
                if "FROM mrt_ad_performance_daily" in sql:
                    return MockResult([{"sku": "YM-001", "cost": 50.0}])
                if "FROM mrt_ads_daily" in sql:
                    return MockResult([{"total_cost": 80.0}])
                if "FROM dim_additional_expense" in sql:
                    return MockResult(result_rows=[])
                raise AssertionError(f"Unexpected query: {sql}")

        svc = ArticleEconomicsService(MockYMCH(), "default")
        res = svc.build(date(2026, 9, 1), date(2026, 9, 30), marketplace="ym")
        items = res["items"]
        sku_row = next(r for r in items if r["sku"] == "YM-001")
        self.assertEqual(sku_row["marketplace"], "ym")
        self.assertEqual(sku_row["offer_id"], "YM-OFFER-1")
        self.assertEqual(sku_row["sales_qty"], 4)
        self.assertEqual(sku_row["revenue"], 2000.0)
        self.assertEqual(sku_row["cogs"], 800.0)
        # Total net accrued must reconcile to 1500.0 exactly
        total_net = sum(r["net_accrued"] for r in items)
        self.assertAlmostEqual(total_net, 1500.0, places=2)
        self.assertAlmostEqual(res["total"]["net_accrued"], 1500.0, places=2)


if __name__ == "__main__":
    unittest.main()
