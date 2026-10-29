"""Additional CIS receipts and COGS absent from domestic sale accruals."""
import json
from collections import defaultdict
from decimal import Decimal

from common.article_economics import AccrualEconomics, number
from common.ozon_buyouts import parse_buyouts


def cis_adjustments(ch, account_id, start, stop):
    params = dict(aid=account_id, start=start, stop=stop)
    snapshots = list(ch.query(
        "SELECT day,payload FROM raw_ozon_buyouts_daily FINAL WHERE account_id={aid:String}"
        " AND day BETWEEN {start:Date} AND {stop:Date} ORDER BY day", parameters=params,
    ).named_results())
    if not snapshots:
        return {}
    postings = sorted({record['posting_number'] for snapshot in snapshots
        for record in parse_buyouts(json.loads(snapshot['payload'], parse_float=Decimal))})
    if not postings:
        return {}
    params['postings'] = postings
    engine = AccrualEconomics()
    for row in ch.query(
        "SELECT payload FROM raw_ozon_finance_ops FINAL WHERE account_id={aid:String}"
        " AND source='accrual_by_day' AND operation_ts>=toDateTime({start:Date},'Europe/Moscow')"
        " AND operation_ts<toDateTime(addDays({stop:Date},1),'Europe/Moscow')"
        " AND JSONExtractString(payload,'unit_number') IN {postings:Array(String)}", parameters=params,
    ).named_results():
        engine.add(json.loads(row['payload'], parse_float=Decimal))
    costs = {str(r['product_id']): number(r['cost']) for r in ch.query(
        "SELECT p.product_id AS product_id,"
        " if(ifNull(oc.cost_price_rub,0)>0,oc.cost_price_rub,ifNull(c.cost_price_rub,0)) AS cost"
        " FROM dim_product AS p FINAL LEFT JOIN v_offer_cost AS oc"
        " ON p.marketplace=oc.marketplace AND p.account_id=oc.account_id AND p.product_id=oc.product_id"
        " LEFT JOIN dim_product_cost AS c FINAL ON p.marketplace=c.marketplace AND p.product_id=toString(c.product_id)"
        " WHERE p.marketplace='ozon' AND p.account_id={aid:String}", parameters=params,
    ).named_results()}
    result = defaultdict(lambda: dict(receipts=Decimal(0), cogs=Decimal(0), qty=Decimal(0), revenue=Decimal(0), commission=Decimal(0)))
    for row in snapshots:
        before = {sku: r['sales_qty']+r['returns_qty']+r['sales_cis'] for sku,r in engine.rows.items()}
        revenue = sum(v["revenue"] for v in engine.rows.values())
        commission = sum(v["commission"] for v in engine.rows.values())
        receipts = engine.buyout_receipts
        engine.add_buyouts(row['day'], json.loads(row['payload'], parse_float=Decimal))
        target = result[str(row['day'])]
        target['revenue'] += sum(v['revenue'] for v in engine.rows.values())-revenue
        target['commission'] += sum(v['commission'] for v in engine.rows.values())-commission
        target['receipts'] += engine.buyout_receipts-receipts
        for sku,r in engine.rows.items():
            units = r['sales_qty']+r['returns_qty']+r['sales_cis']-before.get(sku,Decimal(0))
            target['qty'] += units
            target['cogs'] += units*costs.get(sku,Decimal(0))
    return result
