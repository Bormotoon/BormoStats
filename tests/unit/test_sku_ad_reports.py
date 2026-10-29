import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from collectors.ozon.sku_ad_reports import parse_report, report_is_fresh


class SkuAdsTests(unittest.TestCase):
    def test_cached_report_uses_moscow_day(self):
        today = date(2026, 10, 29)
        self.assertTrue(report_is_fresh(datetime(2026, 10, 28, 21, tzinfo=UTC), today))
        self.assertTrue(report_is_fresh(datetime(2026, 10, 28, 21), today))
        self.assertFalse(report_is_fresh(datetime(2026, 10, 28, 20, 59, tzinfo=UTC), today))

    def test_explicit_sku_and_decimal_comma(self):
        p={'1':{'report':{'rows':[{'sku':'123','date':'27.10.2026','moneySpent':'1 234,56'}],
                           'totals':{'moneySpent':'1234,56'}}}}
        result=parse_report(p,['1'],date(2026,10,27),date(2026,10,27))
        self.assertEqual(result[(date(2026,10,27),'1','123')],Decimal('1234.56'))

    def test_missing_sku_is_not_allocated(self):
        p={'1':{'report':{'rows':[{'date':'27.10.2026','moneySpent':'50'}],'totals':{'moneySpent':'50'}}}}
        self.assertEqual(parse_report(p,['1'],date(2026,10,27),date(2026,10,27)),{})

    def test_independent_rounding_preserves_sku_rows(self):
        rows=[{'sku':'123','date':'27.10.2026','moneySpent':'0,01'} for _ in range(5)]
        p={'1':{'report':{'rows':rows,'totals':{'moneySpent':'0,03'}}}}
        r=parse_report(p,['1'],date(2026,10,27),date(2026,10,27))
        self.assertEqual(r[(date(2026,10,27),'1','123')],Decimal('.05'))

    def test_corrected_campaign_total_does_not_rescale_sku_spend(self):
        p={'1':{'report':{'rows':[{'sku':'123','date':'27.10.2026','moneySpent':'100'}],
                           'totals':{'moneySpent':'80'}}}}
        r=parse_report(p,['1'],date(2026,10,27),date(2026,10,27))
        self.assertEqual(r[(date(2026,10,27),'1','123')],Decimal('100'))

    def test_missing_campaign_and_bad_dates_fail(self):
        with self.assertRaises(ValueError):parse_report({},['1'],date(2026,10,27),date(2026,10,27))
        p={'1':{'report':{'rows':[{'sku':'123','date':'26.10.2026','moneySpent':'1'}],'totals':{'moneySpent':'1'}}}}
        with self.assertRaises(ValueError):parse_report(p,['1'],date(2026,10,27),date(2026,10,27))


if __name__=='__main__':unittest.main()
