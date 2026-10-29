import json
from common.funnel_economics import finance_days, stock_metrics, campaign_kind


def accrual(day, amount=100):
    return json.dumps({"date":day,"total_amount":{"amount":str(amount)},"unit_number":"old-order",
        "posting":{"products":[{"sku":123,"quantity":1,"commission":{
            "sale_amount":{"amount":str(amount)},"sale_price":{"amount":str(abs(amount))},"commission":{"amount":"0"}}}]}})


def test_sales_and_returns_keep_their_event_day():
    rows=finance_days([("a",accrual("2026-10-27")),("a",accrual("2026-10-28",-100))])
    assert [(r["day"],r["sold"],r["returned"]) for r in rows]==[("2026-10-27",1,0),("2026-10-28",0,1)]


def test_buyout_overlap_does_not_move_sale_between_days_or_accounts():
    payload=json.dumps({"products":[{"posting_number":"old-order","sku":123,"quantity":1,"seller_price_per_instance":100,"amount":50}]})
    rows=finance_days([("a",accrual("2026-10-27"))],[("a","2026-10-28",payload),("b","2026-10-28",payload)])
    assert sum(r["sold"] for r in rows if r["account_id"]=="a")==1
    assert sum(r["sold"] for r in rows if r["account_id"]=="b")==1
    assert next(r for r in rows if r["account_id"]=="a" and r["sold"])['day']=='2026-10-27'


def test_stocks_separate_schemes_and_missing_transit():
    assert stock_metrics([{"type":"fbo","available_stock_count":5,"transit_stock_count":2,"return_from_customer_stock_count":1},{"type":"fbs","present":3}])=={"stock":5,"stockFbs":3,"transit":2,"reverse":1}
    assert stock_metrics([{"type":"fbs","present":3}])["transit"] is None


def test_campaign_split_uses_payment_and_strategy_not_its_title():
    assert campaign_kind({'PaymentType':'CPC','productAutopilotStrategy':'MAX_CLICKS'})=='auto'
    assert campaign_kind({'PaymentType':'CPC','productAutopilotStrategy':'TARGET_BIDS'})=='cpc'
    assert campaign_kind({'PaymentType':'CPO','productAutopilotStrategy':'TARGET_BIDS'}) is None
    assert campaign_kind({'title':'авто'}) is None
