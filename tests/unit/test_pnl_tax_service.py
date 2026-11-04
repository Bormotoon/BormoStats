"""Read-time tax overlay must be reversible and distinguish incomplete monthly data."""

import json
import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from app.services.pnl_service import PnlService


class Result:
    def __init__(self, rows):
        self.rows = rows

    def named_results(self):
        return iter(self.rows)


class Database:
    def __init__(self, reports=True, coverage=30):
        self.reports = reports
        self.coverage = coverage
        self.queries = []

    def query(self, sql, **kwargs):
        self.queries.append(sql)
        if "FROM mrt_pnl_monthly" in sql:
            amounts = dict.fromkeys(
                [
                    "revenue_rub",
                    "commission_rub",
                    "logistics_rub",
                    "returns_cost_rub",
                    "storage_rub",
                    "other_costs_rub",
                    "net_accrued_rub",
                    "cogs_rub",
                    "gross_profit_rub",
                    "ad_cost_rub",
                    "additional_expenses_rub",
                    "operating_profit_rub",
                    "ebitda_rub",
                    "margin_pct",
                ],
                0,
            )
            return Result(
                [
                    {
                        **amounts,
                        "month": date(2026, 9, 1),
                        "organization_id": "default",
                        "marketplace": "ozon",
                        "account_id": "default",
                        "net_profit_rub": 2229199.69,
                        "revenue_rub": 1000000,
                        "returns_cost_rub": 10000,
                    }
                ]
            )
        if "FROM raw_ozon_realization_monthly" in sql or "FROM raw_ozon_realization_reports" in sql:
            return Result(
                [
                    {
                        "month": date(2026, 9, 1),
                        "tax_base": Decimal("8411068.19"),
                        "fetched_at": datetime(2026, 10, 28),
                    }
                ]
                if self.reports
                else []
            )
        if "FROM raw_ozon_finance_balance" in sql:
            return Result([{"month": date(2026, 9, 1), "days": self.coverage}])
        if "FROM raw_ozon_finance_ops" in sql:
            return Result(
                [
                    {
                        "payload": json.dumps(
                            {
                                "date": "2026-09-01",
                                "total_amount": 500000,
                                "posting": {
                                    "products": [
                                        {
                                            "sku": 1,
                                            "quantity": 2,
                                            "commission": {
                                                "sale_amount": 990000,
                                                "sale_price": 250000,
                                            },
                                        }
                                    ]
                                },
                            }
                        )
                    }
                ]
            )
        if "FROM raw_ozon_buyouts_daily" in sql or "FROM raw_ozon_cis_buyouts" in sql:
            return Result([])
        if "FROM mrt_finance_daily" in sql:
            return Result([])
        if "FROM dim_product" in sql:
            return Result([])
        raise AssertionError(sql)


class TaxServiceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "PNL_REALIZATION_TAX_ENABLED": "true",
                "PNL_TAX_ORGANIZATION_ID": "default",
                "PNL_TAX_ACCOUNT_ID": "default",
                "PNL_TAX_RATE_PCT": "8",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_september_tax_and_profit(self):
        row = PnlService(Database(), "default").get_pnl()[0]
        self.assertEqual(row.tax_status, "confirmed")
        self.assertEqual(row.tax_rub, 672885.46)
        self.assertEqual(row.net_profit_rub, 1556314.23)
        self.assertEqual(row.profit_before_tax_rub, 2229199.69)

    def test_missing_report_and_incomplete_month(self):
        row = PnlService(Database(reports=False), "default").get_pnl()[0]
        self.assertEqual(row.tax_status, "estimated")
        self.assertEqual(row.tax_rub, 40000)
        self.assertEqual(row.net_profit_rub, 2189199.69)
        row = PnlService(Database(coverage=29), "default").get_pnl()[0]
        self.assertEqual(row.tax_status, "estimated")
        self.assertEqual(row.net_profit_rub, 2189199.69)

    def test_report_automatically_replaces_estimate(self):
        db = Database(reports=False)
        service = PnlService(db, "default")
        self.assertEqual(service.get_pnl()[0].tax_status, "estimated")
        db.reports = True
        row = service.get_pnl()[0]
        self.assertEqual(row.tax_status, "confirmed")
        self.assertEqual(row.net_profit_rub, 1556314.23)

    def test_toggle_restores_original_without_reading_new_table(self):
        os.environ["PNL_REALIZATION_TAX_ENABLED"] = "false"
        db = Database()
        row = PnlService(db, "default").get_pnl()[0]
        self.assertFalse(row.tax_enabled)
        self.assertEqual(row.net_profit_rub, 2229199.69)
        self.assertFalse(
            any("raw_ozon_realization" in q for q in db.queries),
            "Realization tax table must not be queried when tax is disabled",
        )

    def test_other_organization_is_unaffected(self):
        db = Database()
        row = PnlService(db, "another-org").get_pnl()[0]
        self.assertFalse(row.tax_enabled)
        self.assertFalse(
            any("raw_ozon_realization" in q for q in db.queries),
            "Realization tax table must not be queried for other organizations",
        )

    def test_wb_tax_confirmed_and_estimated(self):
        base_amounts = dict.fromkeys(
            [
                "commission_rub",
                "logistics_rub",
                "storage_rub",
                "other_costs_rub",
                "net_accrued_rub",
                "cogs_rub",
                "ad_cost_rub",
                "additional_expenses_rub",
                "operating_profit_rub",
                "ebitda_rub",
            ],
            0,
        )
        pnl_row_closed = {
            **base_amounts,
            "month": date(2026, 9, 1),
            "organization_id": "default",
            "marketplace": "wb",
            "account_id": "default",
            "net_profit_rub": 50000.0,
            "gross_profit_rub": 50000.0,
            "revenue_rub": 100000.0,
            "returns_cost_rub": 0.0,
            "margin_pct": 50.0,
        }
        wb_rep = [
            {
                "account_id": "default",
                "month": date(2026, 9, 1),
                "rows_cnt": 10,
                "retail_base": Decimal("100000.00"),
                "fetched_at": datetime(2026, 10, 5),
            }
        ]

        class WBDatabase:
            def __init__(self, rep=wb_rep):
                self.rep = rep
                self.queries = []

            def query(self, sql, **kwargs):
                self.queries.append(sql)
                if "FROM mrt_pnl_monthly" in sql:
                    return Result([pnl_row_closed])
                if "FROM raw_wb_finance_report" in sql:
                    return Result(self.rep)
                if "FROM mrt_finance_daily" in sql:
                    return Result(
                        [
                            {
                                "account_id": "default",
                                "month": date(2026, 9, 1),
                                "revenue_base": Decimal("90000.00"),
                            }
                        ]
                    )
                raise AssertionError(sql)

        # Closed month with report -> confirmed
        row = PnlService(WBDatabase(), "default").get_pnl()[0]
        self.assertTrue(row.tax_enabled)
        self.assertEqual(row.tax_status, "confirmed")
        self.assertEqual(row.tax_base_rub, 100000.0)
        self.assertEqual(row.tax_rub, 8000.0)
        self.assertEqual(row.net_profit_rub, 42000.0)

        # Without report -> estimated fallback to mrt_finance_daily
        row_no_rep = PnlService(WBDatabase(rep=[]), "default").get_pnl()[0]
        self.assertEqual(row_no_rep.tax_status, "estimated")
        self.assertEqual(row_no_rep.tax_base_rub, 90000.0)
        self.assertEqual(row_no_rep.tax_rub, 7200.0)
        self.assertEqual(row_no_rep.net_profit_rub, 42800.0)

    def test_ym_tax_confirmed_and_estimated(self):
        base_amounts = dict.fromkeys(
            [
                "commission_rub",
                "logistics_rub",
                "storage_rub",
                "other_costs_rub",
                "net_accrued_rub",
                "cogs_rub",
                "ad_cost_rub",
                "additional_expenses_rub",
                "operating_profit_rub",
                "ebitda_rub",
            ],
            0,
        )
        pnl_closed = {
            **base_amounts,
            "month": date(2026, 9, 1),
            "organization_id": "default",
            "marketplace": "ym",
            "account_id": "default",
            "net_profit_rub": 80000.0,
            "gross_profit_rub": 80000.0,
            "revenue_rub": 200000.0,
            "returns_cost_rub": 0.0,
            "margin_pct": 40.0,
        }
        pnl_open = {
            **base_amounts,
            "month": date(2026, 11, 1),
            "organization_id": "default",
            "marketplace": "ym",
            "account_id": "default",
            "net_profit_rub": 40000.0,
            "gross_profit_rub": 40000.0,
            "revenue_rub": 100000.0,
            "returns_cost_rub": 0.0,
            "margin_pct": 40.0,
        }

        class YMDatabase:
            def __init__(self, pnl_row, tx_cnt=5):
                self.pnl_row = pnl_row
                self.tx_cnt = tx_cnt
                self.queries = []

            def query(self, sql, **kwargs):
                self.queries.append(sql)
                if "FROM mrt_pnl_monthly" in sql:
                    return Result([self.pnl_row])
                if "FROM mrt_finance_daily" in sql:
                    return Result(
                        [
                            {
                                "account_id": "default",
                                "month": self.pnl_row["month"],
                                "revenue_base": Decimal(str(self.pnl_row["revenue_rub"])),
                                "tx_cnt": self.tx_cnt,
                            }
                        ]
                    )
                raise AssertionError(sql)

        # Closed month -> confirmed
        row_closed = PnlService(YMDatabase(pnl_closed), "default").get_pnl()[0]
        self.assertTrue(row_closed.tax_enabled)
        self.assertEqual(row_closed.tax_status, "confirmed")
        self.assertEqual(row_closed.tax_base_rub, 200000.0)
        self.assertEqual(row_closed.tax_rub, 16000.0)
        self.assertEqual(row_closed.net_profit_rub, 64000.0)

        # Current/open month -> estimated
        row_open = PnlService(YMDatabase(pnl_open), "default").get_pnl()[0]
        self.assertTrue(row_open.tax_enabled)
        self.assertEqual(row_open.tax_status, "estimated")
        self.assertEqual(row_open.tax_base_rub, 100000.0)
        self.assertEqual(row_open.tax_rub, 8000.0)
        self.assertEqual(row_open.net_profit_rub, 32000.0)


if __name__ == "__main__":
    unittest.main()
