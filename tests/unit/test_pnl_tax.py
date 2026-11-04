"""Tax must use the realization amount, preserve returns, and round only the tax."""

import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from common.pnl_tax import is_tax_applicable, realization_totals, tax_amount


def report(rows):
    return {
        "result": {
            "header": {
                "start_date": "2026-09-01",
                "stop_date": "2026-09-30",
                "currency_sys_name": "RUB",
            },
            "rows": rows,
        }
    }


class PnlTaxTests(unittest.TestCase):
    def test_september_reconciliation_and_wrong_bases(self):
        payload = report(
            [
                {
                    "rowNumber": 1,
                    "seller_price_per_instance": 99999999,
                    "delivery_commission": {
                        "amount": "8667765.18",
                        "total": "9061531.35",
                        "bonus": 10112344.42,
                    },
                    "return_commission": {
                        "amount": "256696.99",
                        "total": "264554.94",
                    },
                }
            ]
        )
        sales, returns = realization_totals(payload, date(2026, 9, 1))
        self.assertEqual(sales - returns, Decimal("8411068.19"))
        self.assertEqual(tax_amount(sales - returns, Decimal(8)), Decimal("672885.46"))
        self.assertEqual(tax_amount(Decimal("8411068"), Decimal(8)), Decimal("672885.44"))

    def test_return_only_month_does_not_create_negative_tax(self):
        sales, returns = realization_totals(
            report([{"rowNumber": 1, "return_commission": {"amount": 100}}]),
            date(2026, 9, 1),
        )
        self.assertEqual(tax_amount(sales - returns, Decimal(8)), Decimal("0.00"))

    def test_zero_report_is_distinct_from_missing(self):
        self.assertEqual(realization_totals(report([]), date(2026, 9, 1)), (Decimal(0), Decimal(0)))
        with self.assertRaises(ValueError):
            realization_totals({}, date(2026, 9, 1))

    def test_bad_period_currency_and_duplicate_rows(self):
        with self.assertRaises(ValueError):
            realization_totals(report([]), date(2026, 8, 1))
        p = report([])
        p["result"]["header"]["currency_sys_name"] = "USD"
        with self.assertRaises(ValueError):
            realization_totals(p, date(2026, 9, 1))
        with self.assertRaises(ValueError):
            realization_totals(report([{"rowNumber": 1}, {"rowNumber": 1}]), date(2026, 9, 1))

    def test_rounding_and_invalid_rate(self):
        self.assertEqual(tax_amount(Decimal("0.10"), Decimal(5)), Decimal("0.01"))
        for rate in [Decimal(-1), Decimal(101), Decimal("NaN")]:
            with self.assertRaises(ValueError):
                tax_amount(Decimal(100), rate)

    def test_non_finite_report_is_rejected(self):
        with self.assertRaises(ValueError):
            realization_totals(
                report([{"rowNumber": 1, "delivery_commission": {"amount": "NaN"}}]),
                date(2026, 9, 1),
            )

    def test_is_tax_applicable(self):
        with patch.dict(os.environ, {"PNL_REALIZATION_TAX_ENABLED": "false"}):
            self.assertFalse(is_tax_applicable("default", "ozon", "default"))

        with patch.dict(
            os.environ,
            {
                "PNL_REALIZATION_TAX_ENABLED": "true",
                "PNL_TAX_ORGANIZATION_ID": "default",
                "PNL_TAX_ACCOUNT_ID": "default",
                "PNL_TAX_MARKETPLACES": "ozon,wb,ym",
            },
        ):
            self.assertTrue(is_tax_applicable("default", "ozon", "default"))
            self.assertTrue(is_tax_applicable("default", "wb", "default"))
            self.assertTrue(is_tax_applicable("default", "ym", "default"))
            self.assertFalse(is_tax_applicable("other_org", "ozon", "default"))
            self.assertFalse(is_tax_applicable("default", "ozon", "other_acc"))
            self.assertFalse(is_tax_applicable("default", "aliexpress", "default"))

        with patch.dict(
            os.environ,
            {
                "PNL_REALIZATION_TAX_ENABLED": "true",
                "PNL_TAX_ORGANIZATION_ID": "default",
                "PNL_TAX_ACCOUNT_ID": "*",
                "PNL_TAX_MARKETPLACES": "ozon,wb",
            },
        ):
            self.assertTrue(is_tax_applicable("default", "ozon", "any_account"))
            self.assertTrue(is_tax_applicable("default", "wb", "wb_acc_1"))
            self.assertFalse(is_tax_applicable("default", "ym", "ym_acc_1"))

        with patch.dict(
            os.environ,
            {
                "PNL_REALIZATION_TAX_ENABLED": "true",
                "PNL_TAX_ORGANIZATION_ID": "default",
                "PNL_TAX_ACCOUNT_ID": "default,wb_main,ozon:cab1",
            },
        ):
            self.assertTrue(is_tax_applicable("default", "ozon", "default"))
            self.assertTrue(is_tax_applicable("default", "wb", "wb_main"))
            self.assertTrue(is_tax_applicable("default", "ozon", "cab1"))
            self.assertFalse(is_tax_applicable("default", "wb", "cab1"))
            self.assertFalse(is_tax_applicable("default", "ym", "other"))


if __name__ == "__main__":
    unittest.main()
