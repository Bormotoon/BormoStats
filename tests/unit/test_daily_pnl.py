"""Daily ranges, monthly reconciliation, returns and calendar expense allocation."""

import json
import os
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.services.daily_pnl_service import DailyPnlService, allocate


class Result:
    def __init__(self, rows=(), values=()):
        self.rows, self.result_rows = rows, values

    def named_results(self):
        return iter(self.rows)


class Database:
    def query(self, sql, **kwargs):
        if (
            sql[: len("SELECT marketplace,account_id FROM dim_account")]
            == "SELECT marketplace,account_id FROM dim_account"
        ):
            return Result(values=[("ozon", "default")])
        if "FROM mrt_finance_daily" in sql:
            return Result(
                [
                    dict(
                        day=date(2026, 9, 1),
                        marketplace="ozon",
                        account_id="default",
                        revenue=200,
                        net_accrued=160,
                        ads=30,
                    )
                ]
            )
        if "FROM stg_sales" in sql:
            return Result(
                [
                    dict(
                        day=date(2026, 9, 1),
                        marketplace="ozon",
                        account_id="default",
                        qty=2,
                        cogs=40,
                        missing_costs=0,
                    )
                ]
            )
        if "FROM mrt_ads_daily" in sql:
            raise AssertionError(
                "Performance spend must not be deducted from finance a second time"
            )
        if "FROM raw_ozon_finance_ops" in sql:
            payload = {
                "date": "2026-09-01",
                "total_amount": 160,
                "posting": {
                    "products": [
                        {
                            "sku": 1,
                            "quantity": 2,
                            "commission": {"sale_amount": 200, "sale_price": 75},
                        }
                    ]
                },
            }
            return Result([{"payload": json.dumps(payload)}])
        if "FROM raw_ozon_buyouts_daily" in sql or "FROM raw_ozon_cis_buyouts" in sql:
            return Result([])
        if "FROM dim_additional_expense" in sql:
            return Result([dict(month=date(2026, 9, 1), amount_rub=30)])
        if "FROM mrt_stock_daily" in sql:
            return Result([])
        if "FROM dim_product" in sql:
            return Result([])
        raise AssertionError(sql)


class DailyTests(unittest.TestCase):
    def test_rounding_and_signed_returns(self):
        self.assertEqual(sum(allocate(Decimal("100"), [Decimal(1)] * 31)), Decimal("100"))
        self.assertEqual(
            allocate(Decimal("8"), [Decimal(120), Decimal(-20)]),
            [Decimal("9.60"), Decimal("-1.60")],
        )

    @patch.dict(
        os.environ,
        {
            "PNL_REALIZATION_TAX_ENABLED": "true",
            "PNL_TAX_ORGANIZATION_ID": "default",
            "PNL_TAX_ACCOUNT_ID": "default",
            "PNL_TAX_RATE_PCT": "8",
        },
    )
    @patch("app.services.daily_pnl_service.PnlService")
    def test_day_equals_same_day_in_month_and_expenses_reconcile(self, pnl):
        pnl.return_value.get_pnl.return_value = [
            SimpleNamespace(
                month="2026-09-01",
                marketplace="ozon",
                account_id="default",
                tax_status="confirmed",
                tax_rub=16,
            )
        ]
        svc = DailyPnlService(Database(), "default")
        month = svc.build(date(2026, 9, 1), date(2026, 9, 30))["items"]
        day = svc.build(date(2026, 9, 1), date(2026, 9, 1))["items"][0]
        self.assertEqual(day, month[0])
        self.assertEqual(day["buyer"], 150)
        self.assertEqual(day["profit"], 103)
        self.assertEqual(day["ads"], 30)
        self.assertEqual(sum(r["tax"] for r in month), 16)
        self.assertEqual(sum(r["external"] for r in month), 30)
        self.assertEqual(sum(r["profit"] for r in month), 74)

    @patch.dict(
        os.environ,
        {
            "PNL_REALIZATION_TAX_ENABLED": "true",
            "PNL_TAX_ORGANIZATION_ID": "default",
            "PNL_TAX_ACCOUNT_ID": "default",
            "PNL_TAX_MARKETPLACES": "ozon,wb,ym",
            "PNL_TAX_RATE_PCT": "8",
        },
    )
    @patch("app.services.daily_pnl_service.PnlService")
    def test_daily_pnl_wb_and_ym_tax_and_buyer_revenue(self, pnl):
        class MultiMktDailyDatabase:
            def query(self, sql, **kwargs):
                if (
                    sql[: len("SELECT marketplace,account_id FROM dim_account")]
                    == "SELECT marketplace,account_id FROM dim_account"
                ):
                    return Result(values=[("wb", "default"), ("ym", "default")])
                if "FROM mrt_finance_daily" in sql:
                    return Result(
                        [
                            dict(
                                day=date(2026, 9, 1),
                                marketplace="wb",
                                account_id="default",
                                revenue=1000,
                                net_accrued=800,
                                ads=0,
                                financing=0,
                            ),
                            dict(
                                day=date(2026, 9, 1),
                                marketplace="ym",
                                account_id="default",
                                revenue=500,
                                net_accrued=400,
                                ads=0,
                                financing=0,
                            ),
                        ]
                    )
                if "FROM stg_sales" in sql:
                    return Result(
                        [
                            dict(
                                day=date(2026, 9, 1),
                                marketplace="wb",
                                account_id="default",
                                qty=5,
                                cogs=200,
                                missing_costs=0,
                            ),
                            dict(
                                day=date(2026, 9, 1),
                                marketplace="ym",
                                account_id="default",
                                qty=2,
                                cogs=100,
                                missing_costs=0,
                            ),
                        ]
                    )
                if "FROM mrt_ads_daily" in sql:
                    return Result(
                        [
                            dict(
                                day=date(2026, 9, 1),
                                marketplace="wb",
                                account_id="default",
                                ads_cost=50,
                            ),
                            dict(
                                day=date(2026, 9, 1),
                                marketplace="ym",
                                account_id="default",
                                ads_cost=25,
                            ),
                        ]
                    )
                if "FROM raw_wb_finance_report" in sql:
                    return Result(
                        [
                            dict(
                                day=date(2026, 9, 1),
                                account_id="default",
                                retail_base=1200,
                            )
                        ]
                    )
                if "FROM dim_additional_expense" in sql:
                    return Result([])
                if "FROM mrt_stock_daily" in sql:
                    return Result([])
                raise AssertionError(sql)

        pnl.return_value.get_pnl.return_value = [
            SimpleNamespace(
                month="2026-09-01",
                marketplace="wb",
                account_id="default",
                tax_status="confirmed",
                tax_rub=96.0,
            ),
            SimpleNamespace(
                month="2026-09-01",
                marketplace="ym",
                account_id="default",
                tax_status="confirmed",
                tax_rub=40.0,
            ),
        ]
        svc = DailyPnlService(MultiMktDailyDatabase(), "default")
        res = svc.build(date(2026, 9, 1), date(2026, 9, 1))
        items = res["items"]
        self.assertEqual(len(items), 1)
        day = items[0]
        # WB buyer (1200 from raw_wb_finance_report) + YM buyer (500 from revenue) = 1700
        self.assertEqual(day["buyer"], 1700)
        # Revenue: 1000 + 500 = 1500
        self.assertEqual(day["revenue"], 1500)
        # Ads: 50 + 25 = 75
        self.assertEqual(day["ads"], 75)
        # Tax: 96 + 40 = 136
        self.assertEqual(day["tax"], 136)
        self.assertEqual(day["tax_status"], "allocated_report")
        self.assertTrue(res["tax_enabled"])


if __name__ == "__main__":
    unittest.main()
