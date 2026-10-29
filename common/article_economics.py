"""Article economics from signed Ozon accruals; missing inputs remain unavailable."""
from collections import defaultdict
from decimal import Decimal

ZERO = Decimal(0)
CENT = Decimal('0.01')
EXPENSES = ('delivery', 'partners', 'promotion', 'fbo', 'other_services', 'compensation', 'other_accruals', 'marketing')
MARKETING = {3, 4, 5, 19, 23, 31, 33, 41, 47, 48, 49, 50, 54, 55, 61, 70, 75, 80, 87, 95, 96, 116, 130}
DELIVERY = {2, 6, 9, 28, 29, 30, 32, 40, 45, 53, 59, 62, 64, 65, 67, 71, 73, 98, 99, 100, 110, 111, 112, 113, 114, 115, 120, 121, 124}
PARTNERS = {1, 13, 16, 17, 42, 43, 44, 56, 63, 66, 68, 97, 106, 107, 108, 109, 122, 123}
FBO = {12, 21, 46, 58, 60, 77, 78, 79, 101, 102, 103, 131, 132, 133, 134, 135}
COMPENSATION = {10, 25, 81, 104}


def number(value):
    if isinstance(value, dict):
        value = value.get('amount')
    if value is None:
        return ZERO
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Non-finite financial amount')
    return result


def category(type_id):
    n = int(type_id or 0)
    return ('marketing' if n in MARKETING else 'delivery' if n in DELIVERY else
            'partners' if n in PARTNERS else 'fbo' if n in FBO else
            'compensation' if n in COMPENSATION else 'other_services')


class AccrualEconomics:
    def __init__(self):
        self.rows = defaultdict(lambda: defaultdict(lambda: ZERO))
        self.pool = defaultdict(lambda: ZERO)
        self.raw_total = ZERO
        self.operations = 0
        self.sale_days = defaultdict(lambda: defaultdict(lambda: ZERO))
        self.campaign_charges = defaultdict(lambda: ZERO)
        self.domestic_sales = defaultdict(lambda: defaultdict(lambda: ZERO))
        self.buyout_receipts=ZERO
        self.buyout_overlap_count=0
        self.cis_sale_days=defaultdict(lambda: defaultdict(lambda: ZERO))
        self.seen_buyouts={}

    def fee(self, sku, fee):
        target = self.rows[str(sku)] if sku else self.pool
        target[category(fee.get('type_id'))] -= number(fee.get('accrued'))

    def add(self, payload):
        before = self.net()
        self.raw_total += number(payload.get('total_amount'))
        self.operations += 1
        posting = payload.get('posting') or {}
        for p in posting.get('products') or []:
            sku = str(p.get('sku') or '')
            if not sku:
                continue
            row = self.rows[sku]
            commission = p.get('commission') or {}
            revenue = number(commission.get('sale_amount'))
            if revenue:
                qty = number(p.get('quantity') or 1)
                signed_qty = -qty if revenue < 0 else qty
                row['sales_qty' if revenue > 0 else 'returns_qty'] += signed_qty
                row['revenue'] += revenue
                row['buyer_revenue'] += abs(number(commission.get('sale_price'))) * signed_qty
                row['revenue_rf'] += revenue
                row['buyer_rf'] += abs(number(commission.get('sale_price'))) * signed_qty
                row['commission_rf'] -= number(commission.get('commission'))
                self.sale_days[sku][str(payload['date'])[:7]] += abs(number(commission.get('sale_price'))) * signed_qty
                row['commission'] -= number(commission.get('commission'))
                if revenue>0 and payload.get('unit_number'):
                    original=self.domestic_sales[(str(payload['unit_number']),sku)]
                    original['quantity']+=qty
                    original['gross']+=revenue
                    original['receipt']+=abs(number(commission.get('sale_price')))*qty
                    original['deduction']-=number(commission.get('commission'))
            delivery = p.get('delivery') or {}
            services = delivery.get('services') or []
            for fee in services:
                self.fee(sku, fee)
            row['other_services'] -= number(delivery.get('total_accrued')) - sum(number(f.get('accrued')) for f in services)
        for item in (payload.get('item_fees') or {}).get('fees') or []:
            for fee in item.get('fees') or []:
                self.fee(item.get('sku'), fee)
        non_item = payload.get('non_item_fee')
        if non_item:
            self.fee(None, non_item)
            if int(non_item.get('type_id') or 0) in {41,75}:
                self.campaign_charges[(str(payload.get('date')),str(payload.get('unit_number')))] -= number(non_item.get('accrued'))
        for fee in (payload.get('container_fees') or {}).get('fees') or []:
            self.fee(None, fee)
        # Keep every remaining money movement. Never drop an unsupported shape.
        remainder = number(payload.get('total_amount')) - (self.net() - before)
        self.pool['other_accruals'] -= remainder

    def net(self):
        return sum(r['revenue'] - r['commission'] - sum(r[e] for e in EXPENSES) for r in self.rows.values()) - sum(self.pool.values())

    def add_buyouts(self,day,payload):
        from .ozon_buyouts import parse_buyouts
        for record in parse_buyouts(payload):
            identity=(record['posting_number'],record['sku'])
            if identity in self.seen_buyouts:
                if self.seen_buyouts[identity]!=record:
                    raise ValueError('Conflicting buyout rows for the same posting/SKU')
                self.buyout_overlap_count+=1
                continue
            self.seen_buyouts[identity]=record
            sku=record['sku'];row=self.rows[sku]
            original=self.domestic_sales.get((record['posting_number'],sku))
            if original:
                # Already booked as a sale: classify it, never add a second sale or receipt.
                self.buyout_overlap_count+=1
                row['sales_qty']-=original['quantity']
                row['sales_cis']+=original['quantity']
                for target,field in [('revenue','gross'),('buyer','receipt'),('commission','deduction')]:
                    row[target+'_rf']-=original[field]
                    row[target+'_cis']+=original[field]
                continue
            row['sales_cis']+=record['quantity']
            row['revenue']+=record['gross']
            row['revenue_cis']+=record['gross']
            row['buyer_revenue']+=record['receipt']
            row['buyer_cis']+=record['receipt']
            row['commission']+=record['deduction']
            row['commission_cis']+=record['deduction']
            self.sale_days[sku][str(day)[:7]]+=record['receipt']
            self.cis_sale_days[sku][str(day)[:7]]+=record['receipt']
            self.buyout_receipts+=record['receipt']
            self.raw_total+=record['receipt']

    def allocate(self):
        # User policy: never spread expenses across articles without a verified SKU.
        original_pool = dict(self.pool)
        for key, amount in original_pool.items():
            if amount:
                self.rows['unallocated'][key] += amount
        self.pool.clear()
        if abs(self.net() - self.raw_total) > CENT:
            raise ValueError('Article attribution does not reconcile to the raw accruals')
        return original_pool

    def bind_ad_costs(self, records):
        """Move verified campaign/day/SKU spend out of the unmatched row, once."""
        linked=ZERO
        matched=set()
        for day,campaign,sku,cost in records:
            key=(str(day),str(campaign))
            if key not in self.campaign_charges:
                continue
            amount=number(cost)
            if amount:
                self.rows[str(sku)]['marketing'] += amount
                self.rows['unallocated']['marketing'] -= amount
                linked += amount
                matched.add(key)
        if abs(self.net()-self.raw_total)>CENT:
            raise ValueError('Performance binding changed the source finance total')
        return linked,len(matched)


def metric_row(values):
    """All unit averages and ratios use the totals; never average article percentages."""
    r = dict(values)
    qty = r['sales_qty'] + r['returns_qty'] + (r.get('cis_qty',r.get('sales_cis',ZERO)) or ZERO)
    r['qty'] = qty
    r['mp_cost'] = sum(r[k] for k in EXPENSES if k != 'marketing')
    r['operating'] = None if r.get('cogs') is None else r['revenue'] - r['commission'] - r['cogs'] - r['mp_cost'] - r['marketing']
    r['profit'] = None if r['operating'] is None or r.get('tax') is None or r.get('external') is None else r['operating'] - r['external'] - r['tax']
    money_keys = ('revenue', 'buyer_revenue', 'commission', 'cogs', 'mp_cost', *EXPENSES, 'operating', 'external', 'tax', 'profit')
    for key in money_keys:
        value = r.get(key)
        r[key + '_unit'] = value / qty if value is not None and qty > 0 else None
        r[key + '_pct'] = value / r['revenue'] if value is not None and r['revenue'] > 0 else None
    r['roi'] = r['profit'] / r['cogs'] if r['profit'] is not None and r.get('cogs') and r['cogs'] > 0 else None
    return r
