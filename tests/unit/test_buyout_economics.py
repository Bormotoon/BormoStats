import unittest
from decimal import Decimal as D
from common.article_economics import AccrualEconomics,metric_row,EXPENSES
from common.ozon_buyouts import parse_buyouts


def buyout(posting='cis'):
    return {'products':[{'sku':123,'posting_number':posting,'offer_id':'article','quantity':1,
        'seller_price_per_instance':100,'buyout_price':45,'amount':45,'deduction_by_category_percent':55}]}


class BuyoutEconomicsTests(unittest.TestCase):
    def engine(self):
        e=AccrualEconomics()
        e.add({'date':'2026-10-27','unit_number':'rf','total_amount':{'amount':'38'},'posting':{'products':[
            {'sku':123,'quantity':1,'commission':{'sale_amount':{'amount':'100'},'sale_price':{'amount':'60'},'commission':{'amount':'-52'}},
             'delivery':{'total_accrued':{'amount':'-10'},'services':[{'type_id':32,'accrued':{'amount':'-10'}}]}}]}})
        return e

    def test_add_cis_sale_without_repeating_delivery(self):
        e=self.engine();e.add_buyouts('2026-10-27',buyout());e.allocate()
        r=e.rows['123']
        self.assertEqual(r['sales_qty'],D(1));self.assertEqual(r['sales_cis'],D(1))
        self.assertEqual(r['revenue'],D(200));self.assertEqual(r['buyer_revenue'],D(105))
        self.assertEqual(r['commission'],D(107));self.assertEqual(r['delivery'],D(10))
        self.assertEqual(e.net(),D(83));self.assertEqual(e.raw_total,D(83))
        self.assertEqual(r['revenue_rf'],D(100));self.assertEqual(r['revenue_cis'],D(100))

    def test_already_recorded_sale_is_only_reclassified(self):
        e=self.engine();e.add_buyouts('2026-10-27',buyout('rf'));e.allocate()
        self.assertEqual(e.net(),D(38));self.assertEqual(e.raw_total,D(38))
        self.assertEqual(e.rows['123']['sales_qty'],D(0))
        self.assertEqual(e.rows['123']['sales_cis'],D(1))
        self.assertEqual(e.buyout_overlap_count,1)

    def test_same_buyout_is_not_counted_on_two_days(self):
        e=self.engine();e.add_buyouts('2026-10-27',buyout());e.add_buyouts('2026-10-28',buyout());e.allocate()
        self.assertEqual(e.rows['123']['sales_cis'],D(1));self.assertEqual(e.buyout_receipts,D(45))

    def test_missing_and_empty_reports_are_different(self):
        self.assertEqual(parse_buyouts({'products':[]}),[])
        with self.assertRaises(ValueError):parse_buyouts({})

    def test_real_deduction_not_domestic_commission(self):
        self.assertEqual(parse_buyouts(buyout())[0]['deduction'],D(55))
        p=buyout();p['products'][0]['quantity']=2;p['products'][0]['amount']=90
        self.assertEqual(parse_buyouts(p)[0]['gross'],D(200))
        self.assertEqual(parse_buyouts(p)[0]['deduction'],D(110))

    def test_metric_quantity_includes_cis_and_returns(self):
        v={key:D(0) for key in (*EXPENSES,'revenue','buyer_revenue','commission','cogs','external','tax')}
        v.update(sales_qty=D(151),returns_qty=D(-3),sales_cis=D(5),revenue=D(712103),cogs=D(119311))
        r=metric_row(v);self.assertEqual(r['qty'],D(153))
        self.assertEqual(r['cogs_unit'],D(119311)/D(153))


if __name__=='__main__':unittest.main()
