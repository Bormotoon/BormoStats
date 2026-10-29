"""Historical Performance API reports: only explicit SKU rows are attributable."""
import time
import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


def report_is_fresh(updated_at, today):
    """Reuse a completed report within one Moscow day; refresh later corrections."""
    stamp = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=UTC)
    return stamp.astimezone(ZoneInfo('Europe/Moscow')).date() == today


def decimal_value(value):
    value = str(value or '0').replace('\u00a0','').replace(' ','').replace(',','.')
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError('Invalid Performance cost')
    return result


def parse_report(data, campaigns, start, stop):
    result = {}
    for campaign in campaigns:
        block = data.get(str(campaign))
        if not isinstance(block,dict) or not isinstance(block.get('report'),dict):
            raise ValueError(f'Performance report missing campaign {campaign}')
        report = block['report']
        rows = report.get('rows')
        if not isinstance(rows,list):
            raise ValueError('Performance report rows are missing')
        known = Decimal(0)
        for row in rows:
            raw_sku = str(row.get('sku') or '')
            if not raw_sku.isdigit() or int(raw_sku)<=0:
                continue
            day = datetime.strptime(row['date'],'%d.%m.%Y').date()
            if not start <= day <= stop:
                raise ValueError('Performance report returned a date outside its period')
            amount = decimal_value(row.get('moneySpent'))
            key = (day,str(campaign),raw_sku)
            result[key] = result.get(key,Decimal(0)) + amount
            known += amount
        # Daily SKU rows and campaign totals can differ after corrections, not only
        # rounding (observed in real 2025 reports). Keep explicit SKU rows unchanged.
        # Finance-versus-SKU differences remain on the unmatched expense article.
    return result


def cache_key(account,campaigns,start,stop):
    return hashlib.sha256(('|'.join([account,start.isoformat(),stop.isoformat(),*sorted(campaigns)])).encode()).hexdigest()


def fetch_report(client, campaigns, start, stop, job_uuid=None, on_created=None):
    headers={'Authorization':'Bearer '+client._access_token(),'Accept':'application/json'}
    uuid=job_uuid
    if not uuid:
        job=client.http.post('/api/client/statistics/json',headers=headers,json={
            'campaigns':campaigns,'dateFrom':start.isoformat(),'dateTo':stop.isoformat(),'groupBy':'DATE'})
        uuid=job.get('UUID')
    if not uuid:
        raise ValueError('Performance did not return a report UUID')
    if on_created:
        on_created(uuid)
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        state=client._get('/api/client/statistics/'+uuid,{})
        if state.get('state')=='OK':
            data=client._get('/api/client/statistics/report',{'UUID':uuid})
            return parse_report(data,campaigns,start,stop),uuid,data
        if state.get('state') in {'ERROR','FAILED'}:
            raise RuntimeError('Performance report generation failed: '+str(state.get('error') or 'unknown error'))
        time.sleep(5)
    raise TimeoutError('Performance report not ready within 10 minutes')
