"""Daily dashboard P&L; calendar allocation is explicit and cent-exact."""
import calendar
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from common.article_economics import AccrualEconomics
from common.pnl_tax import tax_amount
from app.services.pnl_service import PnlService

CENT = Decimal('0.01')


def allocate(amount, weights):
    """Allocate a monthly amount with deterministic rounding; signed returns are allowed."""
    total = sum(weights, Decimal(0))
    if not total:
        weights = [Decimal(1)] * len(weights)
        total = Decimal(len(weights))
    parts = [(amount * w / total).quantize(CENT, rounding=ROUND_HALF_UP) for w in weights]
    if parts:
        parts[-1] += amount - sum(parts)
    return parts


class DailyPnlService:
    def __init__(self, ch, organization_id):
        self.ch, self.org = ch, organization_id

    def build(self, start, stop, marketplace='', account_id=''):
        first = start.replace(day=1)
        last = stop.replace(day=calendar.monthrange(stop.year, stop.month)[1])
        params = dict(oid=self.org, start=first, stop=last, mp=marketplace, aid=account_id)
        scope = " AND (marketplace,account_id) IN (SELECT marketplace,account_id FROM dim_account FINAL WHERE organization_id={oid:String}) AND ({mp:String}='' OR marketplace={mp:String}) AND ({aid:String}='' OR account_id={aid:String})"
        accounts = list(self.ch.query("SELECT marketplace,account_id FROM dim_account FINAL WHERE organization_id={oid:String} AND ({mp:String}='' OR marketplace={mp:String}) AND ({aid:String}='' OR account_id={aid:String})", parameters=params).result_rows)
        rows = defaultdict(lambda: dict(revenue=Decimal(0), net_accrued=Decimal(0), cogs=Decimal(0), ads=Decimal(0), buyer=Decimal(0), tax=Decimal(0), external=Decimal(0), qty=Decimal(0), missing_costs=0, tax_status='disabled'))
        for r in self.ch.query("SELECT day,marketplace,account_id,sales+returns AS revenue,net_accrued,if(marketplace='ozon',-details['loans_and_factoring'],0) AS financing,if(marketplace='ozon',-details['pay_per_click'],0) AS ads FROM mrt_finance_daily FINAL WHERE day BETWEEN {start:Date} AND {stop:Date}" + scope, parameters=params).named_results():
            target = rows[(str(r['day']), r['marketplace'], r['account_id'])]
            for k in ('revenue','net_accrued'):
                target[k] += Decimal(str(r[k]))
            target['ads'] += Decimal(str(r.get('ads') or 0))
            target['net_accrued'] += Decimal(str(r.get('financing') or 0))
        # Same COGS fallback as monthly P&L; never silently hide missing costs.
        sql = """SELECT s.day AS day,s.marketplace AS marketplace,s.account_id AS account_id,
            sum(s.qty) AS qty,
            sum(s.qty * if(ifNull(oc.cost_price_rub,0)>0,oc.cost_price_rub,ifNull(c.cost_price_rub,0))) AS cogs,
            countIf(s.qty!=0 AND ifNull(oc.cost_price_rub,0)<=0 AND ifNull(c.cost_price_rub,0)<=0) AS missing_costs
            FROM stg_sales AS s FINAL
            LEFT JOIN dim_product_cost AS c FINAL ON s.marketplace=c.marketplace AND s.product_id=toString(c.product_id)
            LEFT JOIN v_offer_cost AS oc ON s.marketplace=oc.marketplace AND s.account_id=oc.account_id AND s.product_id=oc.product_id
            WHERE s.day BETWEEN {start:Date} AND {stop:Date}
            AND (s.marketplace,s.account_id) IN (SELECT marketplace,account_id FROM dim_account FINAL WHERE organization_id={oid:String})
            AND ({mp:String}='' OR s.marketplace={mp:String}) AND ({aid:String}='' OR s.account_id={aid:String})
            GROUP BY s.day,s.marketplace,s.account_id"""
        for r in self.ch.query(sql, parameters=params).named_results():
            target=rows[(str(r['day']),r['marketplace'],r['account_id'])]
            for k in ('qty','cogs'):
                target[k] += Decimal(str(r[k]))
            target['missing_costs'] += r['missing_costs']
        # Buyer prices and signed returns, not seller prices or payouts.
        for mp, aid in accounts:
            if mp != 'ozon':
                continue
            p = {**params, 'account':aid}
            engines = defaultdict(AccrualEconomics)
            for r in self.ch.query("SELECT payload FROM raw_ozon_finance_ops FINAL WHERE account_id={account:String} AND source='accrual_by_day' AND operation_ts>=toDateTime({start:Date},'Europe/Moscow') AND operation_ts<toDateTime(addDays({stop:Date},1),'Europe/Moscow')",parameters=p).named_results():
                payload=json.loads(r['payload'],parse_float=Decimal)
                engines[str(payload['date'])[:10]].add(payload)
            domestic={k:v for engine in engines.values() for k,v in engine.domestic_sales.items()}
            seen={}
            for r in self.ch.query("SELECT day,payload FROM raw_ozon_buyouts_daily FINAL WHERE account_id={account:String} AND day BETWEEN {start:Date} AND {stop:Date} ORDER BY day",parameters=p).named_results():
                engine=engines[str(r['day'])]
                engine.domestic_sales.update(domestic)
                engine.seen_buyouts=seen
                payload=json.loads(r['payload'],parse_float=Decimal)
                payload['products']=[v for v in payload['products'] if (str(v.get('posting_number')),str(v.get('sku'))) not in domestic]
                engine.add_buyouts(r['day'],payload)
            for day,engine in engines.items():
                rows[(day,mp,aid)]['buyer']=sum((v['buyer_revenue'] for v in engine.rows.values()),Decimal(0))
        monthly = {(r.month[:7],r.marketplace,r.account_id):r for r in PnlService(self.ch,self.org).get_pnl(first,last,marketplace,account_id) if r.marketplace}
        from app.services.ozon_cis_service import cis_adjustments
        for mp, aid in accounts:
            if mp == 'ozon':
                for day, extra in cis_adjustments(self.ch, aid, first, last).items():
                    target = rows[(day,mp,aid)]
                    target['revenue'] += extra['revenue']
                    target['net_accrued'] += extra['receipts']
                    target['cogs'] += extra['cogs']
                    target['qty'] += extra['qty']
        month=first
        while month<=last:
            count=calendar.monthrange(month.year,month.month)[1]
            days=[month+timedelta(days=i) for i in range(count)]
            for mp,aid in accounts:
                keys=[(d.isoformat(),mp,aid) for d in days]
                monthly_row=monthly.get((month.isoformat()[:7],mp,aid))
                enabled=(os.getenv('PNL_REALIZATION_TAX_ENABLED','false').lower()=='true' and self.org==os.getenv('PNL_TAX_ORGANIZATION_ID','default') and mp=='ozon' and aid==os.getenv('PNL_TAX_ACCOUNT_ID','default'))
                if enabled:
                    weights=[rows[k]['buyer'] for k in keys]
                    confirmed=monthly_row is not None and monthly_row.tax_status=='confirmed'
                    amount=Decimal(str(monthly_row.tax_rub)) if confirmed else tax_amount(sum(weights),Decimal(os.getenv('PNL_TAX_RATE_PCT','8')))
                    for key,part in zip(keys,allocate(amount,weights)):
                        rows[key]['tax']=part
                        rows[key]['tax_status']='allocated_report' if confirmed else 'estimated'
            month=(month.replace(day=28)+timedelta(days=4)).replace(day=1)
        external=defaultdict(Decimal)
        for r in self.ch.query("SELECT month,expense_date,amount_rub FROM dim_additional_expense FINAL WHERE organization_id={oid:String} AND month BETWEEN {start:Date} AND {stop:Date}",parameters=params).named_results():
            if r.get('expense_date') is not None:
                external[str(r['expense_date'])] += Decimal(str(r['amount_rub']))
                continue
            month=r['month']
            if isinstance(month,str): month=date.fromisoformat(month)
            count=calendar.monthrange(month.year,month.month)[1]
            for i,part in enumerate(allocate(Decimal(str(r['amount_rub'])),[Decimal(1)]*count)):
                external[(month+timedelta(days=i)).isoformat()]+=part
        items=[]
        stocks={}
        stock_sql="""SELECT s.day AS day,sum(s.stock_end) AS stock,
            sum(s.stock_end * if(ifNull(oc.cost_price_rub,0)>0,oc.cost_price_rub,ifNull(c.cost_price_rub,0))) AS stock_cost
            FROM mrt_stock_daily AS s FINAL
            LEFT JOIN dim_product_cost AS c FINAL ON s.marketplace=c.marketplace AND s.product_id=toString(c.product_id)
            LEFT JOIN v_offer_cost AS oc ON s.marketplace=oc.marketplace AND s.account_id=oc.account_id AND s.product_id=oc.product_id
            WHERE s.day BETWEEN {start:Date} AND {stop:Date}
            AND (s.marketplace,s.account_id) IN (SELECT marketplace,account_id FROM dim_account FINAL WHERE organization_id={oid:String})
            AND ({mp:String}='' OR s.marketplace={mp:String}) AND ({aid:String}='' OR s.account_id={aid:String}) GROUP BY s.day"""
        for r in self.ch.query(stock_sql,parameters=params).named_results():
            stocks[str(r['day'])]=r
        for i in range((stop-start).days+1):
            day=(start+timedelta(days=i)).isoformat()
            parts=[rows[(day,mp,aid)] for mp,aid in accounts]
            result={k:sum((r[k] for r in parts),Decimal(0)) for k in ('revenue','net_accrued','cogs','ads','buyer','tax','qty')}
            result['external']=external[day] if accounts else Decimal(0)
            # net_accrued already includes every marketplace charge, including ads.
            # Performance statistics are attribution data, not another expense.
            result['before_tax']=result['net_accrued']-result['cogs']-result['external']
            result['profit']=result['before_tax']-result['tax']
            result['missing_costs']=sum(r['missing_costs'] for r in parts)
            result['stock']=stocks.get(day,{}).get('stock')
            result['stock_cost']=stocks.get(day,{}).get('stock_cost')
            active=[r for r in parts if any(r[k] for k in ('revenue','buyer','net_accrued','cogs','ads','tax'))]
            result['tax_status']='estimated' if any(r['tax_status']=='estimated' for r in active) else 'allocated_report' if active and all(r['tax_status']=='allocated_report' for r in active) else 'disabled'
            items.append(dict(day=day,**{k:float(v) if isinstance(v,Decimal) else v for k,v in result.items()}))
        return dict(items=items, notes=['Внешние расходы с датой учитываются целиком в указанный день. Старые расходы без даты распределены поровну по календарным дням месяца; при фильтре кабинета учитываются общие расходы организации.', 'Налог по ценам покупателя за вычетом возвратов; после полного отчёта месячный налог распределяется по дневной базе. Остатки — последний снимок на выбранную дату.'])
