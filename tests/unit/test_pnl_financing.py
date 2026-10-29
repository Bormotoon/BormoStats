import unittest
from types import SimpleNamespace

from app.services.pnl_service import PnlService


class FinancingTests(unittest.TestCase):
    def test_principal_flows_are_excluded_once_with_their_original_sign(self):
        for adjustment in (704660, -1000, 0):
            with self.subTest(adjustment=adjustment):
                db = SimpleNamespace(query=lambda *a, **kw: SimpleNamespace(
                    named_results=lambda: iter([dict(
                        month='2026-07-01', account_id='a', adjustment=adjustment,
                    )])))
                row = SimpleNamespace(
                    month='2026-07-01', marketplace='ozon', account_id='a',
                    other_costs_rub=900000, net_accrued_rub=1000000,
                    gross_profit_rub=500000, operating_profit_rub=400000,
                    ebitda_rub=400000, net_profit_rub=400000,
                )
                PnlService(db, 'org')._apply_financing([row])
                self.assertEqual(row.financing_adjustment_rub, adjustment)
                self.assertEqual(row.other_costs_rub, 900000-adjustment)
                self.assertEqual(row.net_profit_rub, 400000+adjustment)
                self.assertEqual(row.net_accrued_rub, 1000000+adjustment)


if __name__ == '__main__':
    unittest.main()
