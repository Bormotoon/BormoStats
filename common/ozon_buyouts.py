"""Strict reader of the separate EAEU/foreign buyout report."""
from .article_economics import number


def parse_buyouts(payload):
    rows=payload.get('products')
    if not isinstance(rows,list):
        raise ValueError('Buyout report has no products list')
    result=[]
    seen=set()
    for row in rows:
        sku=str(row.get('sku') or '')
        posting=str(row.get('posting_number') or '')
        if not sku.isdigit() or int(sku)<=0 or not posting:
            raise ValueError('Buyout report is missing SKU or posting number')
        key=(posting,sku)
        if key in seen:
            raise ValueError('Duplicate posting/SKU in buyout report')
        seen.add(key)
        for field in ('quantity','seller_price_per_instance','amount'):
            if row.get(field) is None:
                raise ValueError('Missing buyout field: '+field)
        quantity=number(row['quantity'])
        if quantity==0 or quantity!=quantity.to_integral_value():
            raise ValueError('Invalid buyout quantity')
        gross=number(row['seller_price_per_instance'])*quantity
        receipt=number(row['amount'])
        result.append({'sku':sku,'posting_number':posting,'offer_id':str(row.get('offer_id') or ''),
                       'title':str(row.get('name') or ''),'quantity':quantity,
                       'gross':gross,'receipt':receipt,'deduction':gross-receipt})
    return result
