"""Read-time tax overlay must be reversible and distinguish incomplete monthly data."""
import os
import json
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
        if 'FROM mrt_pnl_monthly' in sql:
            amounts = dict.fromkeys(['revenue_rub', 'commission_rub', 'logistics_rub',
                'returns_cost_rub', 'storage_rub', 'other_costs_rub', 'net_accrued_rub',
                'cogs_rub', 'gross_profit_rub', 'ad_cost_rub', 'additional_expenses_rub',
                'operating_profit_rub', 'ebitda_rub', 'margin_pct'], 0)
            return Result([{**amounts, 'month': date(2026, 9, 1), 'organization_id': 'default',
                            'marketplace': 'ozon', 'account_id': 'default',
                            'net_profit_rub': 2229199.69, 'revenue_rub': 1000000, 'returns_cost_rub': 10000}])
        if 'FROM raw_ozon_realization_monthly' in sql:
            return Result([{'month': date(2026, 9, 1), 'tax_base': Decimal('8411068.19'),
                            'fetched_at': datetime(2026, 10, 28)}] if self.reports else [])
        if 'FROM raw_ozon_finance_balance' in sql:
            return Result([{'month': date(2026, 9, 1), 'days': self.coverage}])
        if 'FROM raw_ozon_finance_ops' in sql:
            return Result([{'payload': json.dumps({'date': '2026-09-01', 'total_amount': 500000,
                'posting': {'products': [{'sku': 1, 'quantity': 2,
                    'commission': {'sale_amount': 990000, 'sale_price': 250000}}]}})}])
        if 'FROM raw_ozon_buyouts_daily' in sql:
            return Result([])
        raise AssertionError(sql)


class TaxServiceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'PNL_REALIZATION_TAX_ENABLED': 'true',
            'PNL_TAX_ORGANIZATION_ID': 'default', 'PNL_TAX_ACCOUNT_ID': 'default',
            'PNL_TAX_RATE_PCT': '8'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_september_tax_and_profit(self):
        row = PnlService(Database(), 'default').get_pnl()[0]
        self.assertEqual(row.tax_status, 'confirmed')
        self.assertEqual(row.tax_rub, 672885.46)
        self.assertEqual(row.net_profit_rub, 1556314.23)
        self.assertEqual(row.profit_before_tax_rub, 2229199.69)

    def test_missing_report_and_incomplete_month(self):
        row = PnlService(Database(reports=False), 'default').get_pnl()[0]
        self.assertEqual(row.tax_status, 'estimated')
        self.assertEqual(row.tax_rub, 40000)
        self.assertEqual(row.net_profit_rub, 2189199.69)
        row = PnlService(Database(coverage=29), 'default').get_pnl()[0]
        self.assertEqual(row.tax_status, 'estimated')
        self.assertEqual(row.net_profit_rub, 2189199.69)

    def test_report_automatically_replaces_estimate(self):
        db = Database(reports=False)
        service = PnlService(db, 'default')
        self.assertEqual(service.get_pnl()[0].tax_status, 'estimated')
        db.reports = True
        row = service.get_pnl()[0]
        self.assertEqual(row.tax_status, 'confirmed')
        self.assertEqual(row.net_profit_rub, 1556314.23)

    def test_toggle_restores_original_without_reading_new_table(self):
        os.environ['PNL_REALIZATION_TAX_ENABLED'] = 'false'
        db = Database()
        row = PnlService(db, 'default').get_pnl()[0]
        self.assertFalse(row.tax_enabled)
        self.assertEqual(row.net_profit_rub, 2229199.69)
        self.assertEqual(len(db.queries), 1)

    def test_other_organization_is_unaffected(self):
        db = Database()
        row = PnlService(db, 'another-org').get_pnl()[0]
        self.assertFalse(row.tax_enabled)
        self.assertEqual(len(db.queries), 1)


if __name__ == '__main__':
    unittest.main()
