import unittest
from decimal import Decimal as D
from common.article_economics import AccrualEconomics, EXPENSES, metric_row


class ArticleEconomicsTests(unittest.TestCase):
    def test_sale_return_and_shared_fees_reconcile(self):
        e=AccrualEconomics()
        e.add({'date':'2026-10-27','total_amount':{'amount':'70'},'posting':{'products':[
            {'sku':1,'quantity':1,'commission':{'sale_amount':{'amount':'100'},'sale_price':{'amount':'60'},'commission':{'amount':'-20'}},
             'delivery':{'total_accrued':{'amount':'-10'},'services':[{'type_id':32,'accrued':{'amount':'-10'}}]}}]}})
        e.add({'date':'2026-10-27','total_amount':{'amount':'-40'},'posting':{'products':[
            {'sku':2,'quantity':1,'commission':{'sale_amount':{'amount':'-50'},'sale_price':{'amount':'-30'},'commission':{'amount':'10'}}}]}})
        e.add({'date':'2026-10-27','total_amount':{'amount':'-1.01'},'non_item_fee':{'type_id':41,'accrued':{'amount':'-1.01'}}})
        shared=e.allocate()
        self.assertEqual(e.net(),D('28.99'))
        self.assertEqual(e.rows['2']['buyer_revenue'],D('-30'))
        self.assertEqual(sum(r['marketing'] for r in e.rows.values()),D('1.01'))
        self.assertEqual(shared['marketing'],D('1.01'))
        self.assertEqual(e.rows['1']['marketing'],D(0))
        self.assertEqual(e.rows['unallocated']['marketing'],D('1.01'))

    def test_unknown_operations_are_preserved(self):
        e=AccrualEconomics();e.add({'total_amount':{'amount':'12.33'}})
        e.allocate();self.assertEqual(e.net(),D('12.33'))
        self.assertIn('unallocated',e.rows)

    def test_performance_is_exact_and_keeps_unmatched_cost(self):
        e=AccrualEconomics()
        e.add({'date':'2026-10-27','unit_number':'campaign','total_amount':{'amount':'-5'},
               'non_item_fee':{'type_id':41,'accrued':{'amount':'-5'}}})
        e.allocate()
        linked,_=e.bind_ad_costs([('2026-10-27','campaign','sku1',D('2.50')),
                                 ('2026-10-27','campaign','sku2',D('1.50')),
                                 ('2026-10-27','other','sku3',D(99))])
        self.assertEqual(linked,D(4))
        self.assertEqual(e.rows['sku1']['marketing'],D('2.50'))
        self.assertEqual(e.rows['unallocated']['marketing'],D(1))
        self.assertEqual(e.net(),D(-5))

    def test_weighted_totals_and_missing_cost(self):
        v={k:D(0) for k in (*EXPENSES,'sales_qty','returns_qty','revenue','buyer_revenue','commission','external','tax')}
        v.update(sales_qty=D(3),returns_qty=D(-1),revenue=D(200),commission=D(40),cogs=D(80),tax=D(10))
        row=metric_row(v)
        self.assertEqual(row['revenue_unit'],D(100))
        self.assertEqual(row['operating'],D(80))
        self.assertEqual(row['profit'],D(70))
        self.assertEqual(row['roi'],D('.875'))
        self.assertEqual(row['profit_pct'],D('.35'))
        v['cogs']=None;row=metric_row(v)
        self.assertIsNone(row['profit']);self.assertIsNone(row['cogs_unit'])


if __name__=='__main__':unittest.main()
