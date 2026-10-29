import os
import unittest
from contextlib import nullcontext
from datetime import date
from unittest.mock import patch

from pydantic import ValidationError
from app.models.pnl import AdditionalExpenseCreate, AdditionalExpenseUpdate
from app.services.pnl_service import PnlService, _row_to_expense
from app.services.daily_pnl_service import DailyPnlService
from app.services.article_economics_service import ArticleEconomicsService


class Result:
    def __init__(self, rows=(), values=()):
        self.rows, self.result_rows = rows, values

    def named_results(self):
        return iter(self.rows)


class Database:
    def __init__(self, monthly=False):
        self.monthly = monthly
        self.writes = []

    def command(self, sql, parameters, **kwargs):
        self.writes.append(parameters)

    def query_row_block_stream(self, *args, **kwargs):
        return nullcontext([])

    def query(self, sql, **kwargs):
        if sql.startswith('SELECT marketplace,account_id FROM dim_account'):
            return Result(values=[('ozon', 'default')])
        if sql.startswith('SELECT account_id FROM dim_account'):
            return Result(values=[('default',)])
        if 'FROM dim_additional_expense' in sql:
            entries = [dict(month=date(2026, 9, 1), expense_date=date(2026, 9, 15), amount_rub=125.67)]
            if self.monthly:
                entries.append(dict(month=date(2026, 9, 1), expense_date=None, amount_rub=30))
            return Result(entries, [(r['month'], r['expense_date'], r['amount_rub']) for r in entries])
        return Result()


class ExpenseDatesTests(unittest.TestCase):
    def test_create_derives_month_and_preserves_legacy_month(self):
        db = Database()
        expense = PnlService(db, 'org').create_expense(AdditionalExpenseCreate(
            category='Аренда', amount_rub=125.67, expense_date='2026-09-15'))
        self.assertEqual(expense.month, '2026-09')
        self.assertEqual(db.writes[0]['expense_date'], date(2026, 9, 15))
        self.assertEqual(db.writes[0]['month'], '2026-09-01')
        self.assertEqual(db.writes[0]['organization_id'], 'org')
        legacy = AdditionalExpenseCreate(category='Old', amount_rub=10, month='2026-09')
        self.assertIsNone(legacy.expense_date)

    def test_invalid_or_conflicting_dates_are_rejected(self):
        for fields in [{}, {'expense_date': '2026-02-30'}, {'expense_date': '1960-01-01'},
                       {'month': '2026-13'}, {'expense_date': '2026-09-15', 'month': '2026-10'}]:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                AdditionalExpenseCreate(category='Rent', amount_rub=10, **fields)

    def test_date_roundtrip_and_update_month(self):
        old = _row_to_expense(dict(expense_id='id', organization_id='org', category='Rent',
            amount_rub=10, month=date(2026, 9, 1), expense_date=date(2026, 9, 15), description=''))
        db = Database()
        with patch.object(PnlService, 'get_expense', return_value=old):
            updated = PnlService(db, 'org').update_expense('id', AdditionalExpenseUpdate(expense_date='2026-10-01'))
        self.assertEqual(updated.month, '2026-10')
        self.assertEqual(updated.expense_date, date(2026, 10, 1))

    @patch.dict(os.environ, {'PNL_REALIZATION_TAX_ENABLED': 'false'})
    @patch('app.services.daily_pnl_service.PnlService')
    def test_daily_cost_is_not_spread_and_legacy_cost_still_reconciles(self, pnl):
        pnl.return_value.get_pnl.return_value = []
        svc = DailyPnlService(Database(monthly=True), 'org')
        month = svc.build(date(2026, 9, 1), date(2026, 9, 30))['items']
        self.assertAlmostEqual(sum(r['external'] for r in month), 155.67)
        self.assertEqual(month[14]['external'], 126.67)
        self.assertEqual(month[13]['external'], 1)
        self.assertEqual(month[14]['profit'], -126.67)
        single = svc.build(date(2026, 9, 15), date(2026, 9, 15))['items'][0]
        self.assertEqual(single, month[14])

    @patch.dict(os.environ, {'PNL_REALIZATION_TAX_ENABLED': 'false'})
    def test_economics_includes_only_actual_day_and_preserves_unknown_monthly(self):
        svc = ArticleEconomicsService(Database(), 'org')
        day = svc.build(date(2026, 9, 15), date(2026, 9, 15))
        self.assertEqual(day['total']['external'], 125.67)
        self.assertFalse(day['external_period_incomplete'])
        outside = svc.build(date(2026, 9, 16), date(2026, 9, 16))
        self.assertEqual(outside['total']['external'], 0)
        legacy = ArticleEconomicsService(Database(monthly=True), 'org')
        self.assertTrue(legacy.build(date(2026, 9, 15), date(2026, 9, 15))['external_period_incomplete'])
        full = legacy.build(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(full['total']['external'], 155.67)
        self.assertFalse(full['external_period_incomplete'])
