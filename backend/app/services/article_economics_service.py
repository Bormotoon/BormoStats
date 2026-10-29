"""Per-article economics, independently reconcilable to the source financial accruals."""
import calendar
import json
import os
from datetime import date,timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from common.article_economics import AccrualEconomics, EXPENSES, ZERO, metric_row, number
from common.pnl_tax import tax_amount
from common.ozon_buyouts import parse_buyouts

REFERENCE_IMAGES=json.loads((Path(__file__).resolve().parents[3]/'common'/'economics_reference_images.json').read_text(encoding='utf-8'))


class ArticleEconomicsService:
    def __init__(self, ch, organization_id):
        self.ch = ch
        self.org = organization_id

    def build(self, date_from, date_to, account_id=None):
        params = {'oid': self.org, 'start': date_from, 'stop': date_to}
        accounts = [r[0] for r in self.ch.query(
            "SELECT account_id FROM dim_account FINAL WHERE organization_id={oid:String} AND marketplace='ozon'",
            parameters=params).result_rows]
        if account_id:
            accounts = [a for a in accounts if a == account_id]
        if not accounts:
            return {'items': [], 'total': None, 'notes': ['Нет доступных кабинетов Ozon.']}
        params['accounts'] = accounts
        catalogue = list(self.ch.query(
            "SELECT product_id,offer_id,title,image_url FROM dim_product FINAL WHERE marketplace='ozon' AND account_id IN {accounts:Array(String)}",
            parameters=params).named_results())
        cards = {str(r['product_id']): r for r in catalogue}
        offer_costs = {r[0]: number(r[1]) for r in self.ch.query(
            "SELECT offer_id,cost_price_rub FROM dim_offer_cost FINAL WHERE organization_id={oid:String}", parameters=params).result_rows}
        sku_costs = {str(r[0]): number(r[1]) for r in self.ch.query(
            "SELECT product_id,cost_price_rub FROM dim_product_cost FINAL WHERE marketplace='ozon'").result_rows}
        engine = AccrualEconomics()
        sql = """SELECT payload FROM raw_ozon_finance_ops FINAL
          WHERE account_id IN {accounts:Array(String)} AND source='accrual_by_day'
          AND operation_ts >= toDateTime({start:Date}, 'Europe/Moscow')
          AND operation_ts < toDateTime(addDays({stop:Date},1), 'Europe/Moscow')"""
        # Bounded memory even for the full year's raw JSON documents.
        with self.ch.query_row_block_stream(sql, parameters=params, settings={'max_block_size': 1024}) as stream:
            for block in stream:
                for (raw,) in block:
                    engine.add(json.loads(raw, parse_float=Decimal))
        finance_only_total=engine.raw_total
        snapshots=self.ch.query(
            'SELECT account_id,day,payload FROM raw_ozon_buyouts_daily FINAL'
            ' WHERE account_id IN {accounts:Array(String)} AND day>={start:Date} AND day<={stop:Date}',parameters=params).result_rows
        covered=set()
        for account,day,raw in snapshots:
            payload=json.loads(raw,parse_float=Decimal)
            engine.add_buyouts(day,payload)
            covered.add((account,day))
            for record in parse_buyouts(payload):
                cards.setdefault(record['sku'],{'offer_id':record['offer_id'],'title':record['title']})
        requested_days=[date_from+timedelta(days=i) for i in range((date_to-date_from).days+1)]
        cis_missing_days=sorted({day.isoformat() for account in accounts for day in requested_days if (account,day) not in covered})
        cis_complete=not cis_missing_days
        allocated = engine.allocate()
        sku_ads = self.ch.query(
            "SELECT day,campaign_id,sku,cost FROM raw_ozon_ads_sku_daily FINAL"
            " WHERE account_id IN {accounts:Array(String)} AND day>={start:Date} AND day<={stop:Date}",parameters=params).result_rows
        linked_ads,matched_campaigns=engine.bind_ad_costs(sku_ads)
        if linked_ads:
            allocated['marketing']=allocated.get('marketing',ZERO)-linked_ads
        tax_enabled = (os.getenv('PNL_REALIZATION_TAX_ENABLED', 'false').lower() == 'true'
                       and self.org == os.getenv('PNL_TAX_ORGANIZATION_ID', 'default'))
        rate = number(os.getenv('PNL_TAX_RATE_PCT', '8'))
        # Replace daily estimates only for full selected calendar months with a validated report.
        report_bases = {}
        if tax_enabled:
            for month, raw in self.ch.query(
                "SELECT month,payload FROM raw_ozon_realization_monthly FINAL WHERE account_id IN {accounts:Array(String)}"
                " AND month>=toStartOfMonth({start:Date}) AND month<=toStartOfMonth({stop:Date})", parameters=params).result_rows:
                last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
                if date_from <= month and date_to >= last:
                    key = month.isoformat()[:7]
                    if key not in report_bases:
                        report_bases[key] = {}
                    for item in json.loads(raw, parse_float=Decimal)['result']['rows']:
                        sku = str(item['item']['sku'])
                        amount = number((item.get('delivery_commission') or {}).get('amount')) - number((item.get('return_commission') or {}).get('amount'))
                        report_bases[key][sku] = report_bases[key].get(sku, ZERO) + amount
            # Separate buyout receipts are absent from the ordinary realization rows.
            for sku,months in engine.cis_sale_days.items():
                for key,receipt in months.items():
                    if key in report_bases:
                        report_bases[key][sku]=report_bases[key].get(sku,ZERO)+receipt
        taxes = {sku: ZERO for sku in engine.rows}
        tax_estimate = False
        monthly_keys = set(m for months in engine.sale_days.values() for m in months) | set(report_bases)
        for month in monthly_keys:
            bases = report_bases.get(month)
            if bases is None:
                bases = {sku: months.get(month, ZERO) for sku, months in engine.sale_days.items()}
                tax_estimate = True
            monthly_tax = tax_amount(sum(bases.values()), rate) if tax_enabled else ZERO
            parts = {sku: (base*rate/Decimal(100)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                     if tax_enabled else ZERO for sku,base in bases.items()}
            rounding = monthly_tax - sum(parts.values())
            if rounding:
                parts['unallocated'] = parts.get('unallocated',ZERO) + rounding
            for sku, amount in parts.items():
                if sku in engine.rows or amount:
                    engine.rows[sku]
                    taxes[sku] = taxes.get(sku, ZERO) + amount
        # Use the same calendar tax allocation as the daily/monthly P&L for
        # partial months too; preserve the SKU attribution weights.
        if tax_enabled:
            from app.services.daily_pnl_service import DailyPnlService, allocate
            daily = DailyPnlService(self.ch, self.org).build(date_from, date_to, 'ozon', account_id or '')
            target_tax = sum((number(r['tax']) for r in daily['items']), ZERO)
            skus = list(taxes)
            if not skus and target_tax:
                skus = ['unallocated']
                engine.rows['unallocated']
            if skus:
                taxes = dict(zip(skus, allocate(target_tax, [taxes.get(s, ZERO) for s in skus]), strict=True))
        # A monthly expense cannot be attributed to individual days without its actual date.
        external = ZERO
        external_unknown = False
        for month, expense_date, amount in self.ch.query(
            "SELECT month,expense_date,amount_rub FROM dim_additional_expense FINAL WHERE organization_id={oid:String}"
            " AND month>=toStartOfMonth({start:Date}) AND month<=toStartOfMonth({stop:Date})", parameters=params).result_rows:
            if expense_date is not None:
                if date_from <= expense_date <= date_to:
                    external += number(amount)
                continue
            last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
            if date_from <= month and date_to >= last:
                external += number(amount)
            elif number(amount):
                from app.services.daily_pnl_service import allocate
                count = calendar.monthrange(month.year, month.month)[1]
                portions = allocate(number(amount), [Decimal(1)] * count)
                external += sum((part for i,part in enumerate(portions)
                    if date_from <= month+timedelta(days=i) <= date_to), ZERO)
        if external or external_unknown:
            engine.rows['unallocated']
        items = []
        missing = []
        period = date_from.strftime('%d.%m') if date_from == date_to else f'{date_from:%d.%m.%Y}–{date_to:%d.%m.%Y}'
        for sku, source in engine.rows.items():
            r = {key: source[key] for key in (*EXPENSES, 'sales_qty', 'returns_qty', 'revenue', 'buyer_revenue', 'commission', 'allocated_cost',
                'sales_cis','revenue_rf','revenue_cis','buyer_rf','buyer_cis','commission_rf','commission_cis')}
            r['cis_qty']=r['sales_cis']
            card = cards.get(sku, {})
            offer = card.get('offer_id') or ('Расходы без привязки' if sku=='unallocated' else f'SKU {sku}')
            cost = offer_costs.get(offer, sku_costs.get(sku))
            units = r['sales_qty'] + r['returns_qty'] + r['cis_qty']
            r['cogs'] = cost * units if cost is not None else ZERO if not units else None
            if r['cogs'] is None:
                missing.append(offer)
            r['external'] = (None if external_unknown else external) if sku=='unallocated' else ZERO
            r['tax'] = taxes.get(sku,ZERO) if tax_enabled else ZERO
            r['tax_main'] = r['tax']
            r = metric_row(r)
            r.update(sku=sku, offer_id=offer, title=card.get('title') or '', image_url=card.get('image_url') or REFERENCE_IMAGES.get(offer), period=period)
            if not cis_complete:
                for key in ('revenue_cis','buyer_cis','commission_cis','sales_cis'):
                    r[key]=None
            r.update(self_purchases=None,vat=None)
            items.append(r)
        for key, letter in [('revenue','revenue_abc'),('operating','operating_abc'),('profit','profit_abc')]:
            candidates = sorted((r for r in items if r[key] is not None and r[key]>0),key=lambda r:-r[key])
            denom = sum(r[key] for r in candidates)
            running = ZERO
            for r in candidates:
                r[letter] = 'A' if running < denom*Decimal('.8') else 'B' if running < denom*Decimal('.95') else 'C'
                running += r[key]
            for r in items:
                r[letter] = r.get(letter, '—' if r[key] is None else 'C')
        for r in items:
            r['abc'] = r['revenue_abc']+r['operating_abc']+r['profit_abc']
        items.sort(key=lambda r: -r['revenue'])
        additive = (*EXPENSES,'sales_qty','returns_qty','revenue','buyer_revenue','commission','cogs','external','tax','tax_main','allocated_cost',
                    'cis_qty','sales_cis','revenue_rf','revenue_cis','buyer_rf','buyer_cis','commission_rf','commission_cis')
        total = metric_row({key: None if any(r.get(key) is None for r in items) else sum((r[key] for r in items), ZERO) for key in additive})
        total.update(offer_id='Итого',period='Итого',abc='—',sku='total',image_url=None)
        def serial(row):
            return {k:float(v.quantize(Decimal('.000001'))) if isinstance(v,Decimal) else v for k,v in row.items()}
        return {'items':[serial(r) for r in items], 'total':serial(total), 'from':date_from.isoformat(), 'to':date_to.isoformat(),
                'tax_rate_pct':float(rate), 'tax_enabled':tax_enabled, 'tax_estimate':tax_enabled and tax_estimate,
                'missing_costs':missing, 'operations':engine.operations, 'source_net_accrued':float(engine.raw_total),
                'source_finance_accruals':float(finance_only_total),'cis_buyout_receipts':float(engine.buyout_receipts),
                'cis_coverage_complete':cis_complete,'cis_missing_days':cis_missing_days,
                'cis_days_loaded':len(covered),'cis_overlap_prevented':engine.buyout_overlap_count,
                'unattributed_costs':{k:float(v) for k,v in allocated.items()},
                'ads_sku_linked':float(linked_ads), 'ads_campaign_days_linked':matched_campaigns,
                'external_period_incomplete':external_unknown,
                'notes':['Расходы без подтверждённого SKU сохранены в строке «Расходы без привязки». Пропорционального распределения между артикулами нет.',
                         'СНГ/ЕАЭС: отдельный отчёт /v1/finance/products/buyout; сумма продаж включена один раз по отправлению и SKU. Доставка уже учтена в основной ленте и повторно не начисляется.',
                         'Комиссия/скидка СНГ = цена продавца × количество − фактическая сумма к начислению в отчёте выкупов. Общая ставка комиссии РФ вместо неё не подставляется.',
                         'Нет загруженного отчёта СНГ за день — это отсутствие данных, не ноль. Самовыкупы и отдельный НДС пока не настроены.',
                         'ABC: выручка / операционная прибыль / чистая прибыль; границы 80% и 95%.',
                         'Реклама: фактический расход по SKU из Performance API. Сопоставление с начислениями по дню и кампании; остаток и разница сумм сохранены в строке «Расходы без привязки», повторно не вычитаются.',
                         'Внешние расходы с датой учитываются в указанный день в строке без привязки. Старые месячные расходы учитываются целиком за полный месяц; за фрагмент месяца распределяются по календарным дням, как в P&L.',
                         'Налог за полный закрытый месяц — по реализации; за отдельные дни используется календарное распределение месячного налога, как в P&L; открытые месяцы предварительные.']}
