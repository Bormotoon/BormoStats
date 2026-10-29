"""Funnel endpoints."""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AnalyticsReadAuth
from app.core.deps import ChClientDependency, QueryCacheDependency
from app.models.api import (
    DateRangeQueryParams,
    build_paginated_response,
    get_date_range_query_params,
)
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/funnel", tags=["funnel"], responses=API_ERROR_RESPONSES)


@router.get("/daily")
def funnel_daily(
    *,
    auth: AnalyticsReadAuth,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
    client: ChClientDependency,
    cache: QueryCacheDependency,
) -> dict[str, object]:
    service = MetricsService(client, cache)
    items = service.funnel_daily(
        organization_id=auth.organization_id,
        date_from=filters.date_from,
        date_to=filters.date_to,
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        limit=filters.query_limit,
        offset=filters.offset,
    )
    return build_paginated_response(
        items=items,
        limit=filters.limit,
        offset=filters.offset,
        **{
            "from": filters.date_from.isoformat(),
            "to": filters.date_to.isoformat(),
        },
    )


# Ozon's daily funnel report is supplied by the seller, not by the API.
from datetime import date
from pydantic import BaseModel, Field, model_validator
from fastapi import HTTPException
from app.core.auth import CatalogWriteAuth
from app.db.ch import query_dicts
from app.services.tenancy import ensure_account_access, AccountAccessError


class OzonFunnelRow(BaseModel):
    day: date
    sku: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    scheme: str = Field(default="", max_length=40)
    offer_id: str = Field(default="", max_length=300)
    title: str = Field(default="", max_length=1000)
    position: float = Field(ge=0, le=1000000, allow_inf_nan=False)
    impressions: int = Field(ge=0, le=1000000000000)
    search_impressions: int = Field(ge=0, le=1000000000000)
    clicks: int = Field(ge=0, le=1000000000000)
    carts: int = Field(ge=0, le=1000000000000)


class OzonFunnelImport(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)
    rows: list[OzonFunnelRow] = Field(min_length=1, max_length=200000)

    @model_validator(mode="after")
    def unique_rows(self):
        keys = [(r.day, r.sku, r.scheme) for r in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError("Повторяются строки с одинаковыми датой, SKU и схемой работы")
        return self


@router.post("/ozon/import")
def import_ozon_funnel(payload: OzonFunnelImport, auth: CatalogWriteAuth, client: ChClientDependency):
    try:
        ensure_account_access(client, auth.organization_id, "ozon", payload.account_id)
    except AccountAccessError as exc:
        raise HTTPException(status_code=404, detail="Кабинет Ozon не найден") from exc
    cols = ["account_id", "day", "sku", "scheme", "offer_id", "title", "position", "impressions", "search_impressions", "clicks", "carts"]
    client.insert("ozon_funnel_import", [[payload.account_id, r.day, r.sku, r.scheme, r.offer_id, r.title, r.position, r.impressions, r.search_impressions, r.clicks, r.carts] for r in payload.rows], column_names=cols)
    return {"imported": len(payload.rows)}


@router.get("/ozon")
def ozon_funnel(auth: AnalyticsReadAuth, client: ChClientDependency, filters: DateRangeQueryParams = Depends(get_date_range_query_params)):
    # Deliberately uncached: imports must be visible immediately.
    rows = query_dicts(client, """SELECT day, account_id, sku, scheme, offer_id, title, position, impressions, search_impressions, clicks, carts
      FROM ozon_funnel_import FINAL
      WHERE day BETWEEN %(date_from)s AND %(date_to)s
      AND (%(account_id)s = '' OR account_id = %(account_id)s)
      AND account_id IN (SELECT account_id FROM dim_account FINAL WHERE marketplace = 'ozon' AND organization_id = %(organization_id)s)
      ORDER BY day, sku, scheme LIMIT %(limit)s OFFSET %(offset)s""",
      {"date_from": filters.date_from, "date_to": filters.date_to, "account_id": filters.account_id, "organization_id": auth.organization_id, "limit": filters.query_limit, "offset": filters.offset})
    return build_paginated_response(items=rows, limit=filters.limit, offset=filters.offset, **{"from": filters.date_from.isoformat(), "to": filters.date_to.isoformat()})


@router.get("/ozon/related")
def ozon_funnel_related(auth: AnalyticsReadAuth, client: ChClientDependency, filters: DateRangeQueryParams = Depends(get_date_range_query_params)):
    # Posting status is current, while the day is the order day. Ad amounts are only
    # those directly attributed to a SKU by the Performance report.
    sql = """
    WITH scoped AS (
      SELECT account_id FROM dim_account FINAL
      WHERE marketplace = 'ozon' AND organization_id = %(organization_id)s
        AND (%(account_id)s = '' OR account_id = %(account_id)s)
    ), postings AS (
      SELECT account_id, posting_number,
        argMax(created_at, ingested_at) AS created, argMax(status, ingested_at) AS status
      FROM raw_ozon_postings FINAL WHERE account_id IN scoped
      GROUP BY account_id, posting_number
    ), items AS (
      SELECT account_id, posting_number, ozon_product_id,
        argMax(quantity, ingested_at) AS quantity, argMax(price, ingested_at) AS price
      FROM raw_ozon_posting_items FINAL WHERE account_id IN scoped AND ozon_product_id != 0
      GROUP BY account_id, posting_number, ozon_product_id
    ), returns AS (
      SELECT account_id, assumeNotNull(posting_number) AS posting_number, assumeNotNull(product_id) AS sku,
        -sumIf(qty, qty < 0) AS returned
      FROM stg_sales FINAL WHERE marketplace='ozon' AND account_id IN scoped
        AND posting_number IS NOT NULL AND product_id IS NOT NULL
      GROUP BY account_id, posting_number, product_id
    ), joined AS (
      SELECT p.account_id AS account_id, p.created AS created, p.status AS status,
        i.ozon_product_id AS sku, i.quantity AS quantity, i.price AS price,
        least(toInt64(i.quantity), greatest(toInt64(ifNull(r.returned, 0)), 0)) AS returned
      FROM postings p INNER JOIN items i ON p.account_id = i.account_id AND p.posting_number = i.posting_number
      LEFT JOIN returns r ON p.account_id = r.account_id AND p.posting_number = r.posting_number AND toString(i.ozon_product_id) = r.sku
    )
    SELECT kind, day, account_id, sku, sum(qty) AS qty, sum(amount) AS amount FROM (
      SELECT 'orders' AS kind, toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') AS day,
        account_id, toString(sku) AS sku,
        toFloat64(quantity) AS qty, toFloat64(quantity * price) AS amount
      FROM joined WHERE day BETWEEN %(date_from)s AND %(date_to)s
      UNION ALL
      SELECT 'cancelled' AS kind, toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') AS day,
        account_id, toString(sku) AS sku, toFloat64(quantity) AS qty, toFloat64(quantity * price) AS amount
      FROM joined WHERE status = 'cancelled' AND day BETWEEN %(date_from)s AND %(date_to)s
      UNION ALL
      SELECT 'pending' AS kind, toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') AS day,
        account_id, toString(sku) AS sku, toFloat64(quantity) AS qty, toFloat64(quantity * price) AS amount
      FROM joined WHERE status NOT IN ('delivered', 'cancelled') AND day BETWEEN %(date_from)s AND %(date_to)s
      UNION ALL
      SELECT 'cohort_delivered' AS kind, toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') AS day,
        account_id,toString(sku) AS sku,toFloat64(quantity-returned) AS qty,toFloat64(quantity) AS amount
      FROM joined WHERE status='delivered' AND day BETWEEN %(date_from)s AND %(date_to)s
      UNION ALL
      SELECT 'history' AS kind, toDate(%(date_from)s) AS day, account_id, toString(sku) AS sku,
        toFloat64(if(status = 'delivered', quantity - returned, 0)) AS qty,
        toFloat64(if(status = 'cancelled', quantity, returned)) AS amount
      FROM joined
      WHERE status IN ('delivered', 'cancelled')
        AND toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') >= subtractDays(toDate(%(date_from)s), 90)
        AND toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') < toDate(%(date_from)s)
      UNION ALL
      SELECT 'cost' AS kind, toDate(%(date_from)s) AS day, i.account_id AS account_id, i.sku AS sku,
        0. AS qty, toFloat64(c.cost_price_rub) AS amount
      FROM (
        SELECT account_id, product_id AS sku, any(offer_id) AS offer_id
        FROM dim_product FINAL
        WHERE marketplace = 'ozon' AND account_id IN scoped
        GROUP BY account_id, product_id
      ) i INNER JOIN dim_offer_cost c FINAL
        ON c.organization_id = %(organization_id)s AND c.offer_id = i.offer_id
      UNION ALL
      SELECT 'ads' AS kind, day, account_id, sku, 0. AS qty, toFloat64(cost) AS amount
      FROM raw_ozon_ads_sku_daily FINAL
      WHERE account_id IN scoped AND day BETWEEN %(date_from)s AND %(date_to)s
      UNION ALL
      SELECT 'stock' AS kind, day, account_id, product_id AS sku, toFloat64(stock_end) AS qty, 0. AS amount
      FROM mrt_stock_daily FINAL WHERE marketplace = 'ozon' AND account_id IN scoped
        AND day BETWEEN %(date_from)s AND %(date_to)s
    ) GROUP BY kind, day, account_id, sku
    ORDER BY day, kind, account_id, sku LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"date_from": filters.date_from, "date_to": filters.date_to, "account_id": filters.account_id, "organization_id": auth.organization_id, "limit": filters.query_limit, "offset": filters.offset}
    rows = query_dicts(client, sql, params)
    return build_paginated_response(items=rows, limit=filters.limit, offset=filters.offset, **{"from": filters.date_from.isoformat(), "to": filters.date_to.isoformat()})


@router.get("/ozon/finance")
def ozon_funnel_finance(auth: AnalyticsReadAuth, client: ChClientDependency,
                       filters: DateRangeQueryParams = Depends(get_date_range_query_params)):
    """Finance events by realization day, never by the posting's order day."""
    import json
    import os
    from datetime import timedelta
    from common.funnel_economics import finance_days, stock_metrics, campaign_kind
    params = {"org": auth.organization_id, "account": filters.account_id,
              "start": filters.date_from - timedelta(days=90), "stop": filters.date_to}
    scoped = "SELECT account_id FROM dim_account FINAL WHERE marketplace='ozon' AND organization_id=%(org)s AND (%(account)s='' OR account_id=%(account)s)"
    finance = client.query("SELECT account_id,payload FROM raw_ozon_finance_ops FINAL WHERE account_id IN (" + scoped + ") AND source='accrual_by_day' AND toDate(JSONExtractString(payload,'date')) BETWEEN %(start)s AND %(stop)s", parameters=params).result_rows
    buyouts = client.query("SELECT account_id,day,payload FROM raw_ozon_buyouts_daily FINAL WHERE account_id IN (" + scoped + ") AND day BETWEEN %(start)s AND %(stop)s ORDER BY day", parameters=params).result_rows
    daily = finance_days(finance, buyouts)
    params['start'] = filters.date_from
    metadata = client.query("SELECT account_id,campaign_id,effective_from,payload FROM raw_ozon_campaign_metadata FINAL WHERE account_id IN (" + scoped + ") ORDER BY effective_from", parameters=params).result_rows
    campaign_types = {}
    for account, campaign, effective, raw in metadata:
        campaign_types.setdefault((account,campaign), []).append((effective.date().isoformat(), json.loads(raw)))
    ad_rows = client.query("SELECT account_id,day,sku,campaign_id,cost FROM raw_ozon_ads_sku_daily FINAL WHERE account_id IN (" + scoped + ") AND day BETWEEN %(start)s AND %(stop)s", parameters=params).result_rows
    advertising = []
    for a,d,s,c,cost in ad_rows:
        known = [p for effective,p in campaign_types.get((a,c),[]) if effective <= str(d)]
        record = known[-1] if known else {}
        advertising.append(dict(account_id=a,day=str(d),sku=s,campaign_id=c,amount=float(cost),
                                kind=campaign_kind(record),strategy=record.get('productAutopilotStrategy'),
                                placement=record.get('placement'),title=record.get('title','')))
    stocks = client.query("""SELECT account_id,toDate(toDateTime(toString(snapshot_ts),'UTC'),'Europe/Moscow') AS day,
      toString(ozon_product_id),payload FROM raw_ozon_stocks FINAL
      WHERE account_id IN (""" + scoped + """) AND day BETWEEN %(start)s AND %(stop)s
      AND (account_id,snapshot_ts) IN (
        SELECT account_id,max(snapshot_ts) FROM raw_ozon_stocks FINAL
        WHERE account_id IN (""" + scoped + """)
        GROUP BY account_id,toDate(toDateTime(toString(snapshot_ts),'UTC'),'Europe/Moscow'))""", parameters=params).result_rows
    stock_parts = {}
    for account, day, sku, raw in stocks:
        stock_parts.setdefault((account, str(day), sku), []).extend(json.loads(raw))
    stock_rows = [dict(account_id=account, day=day, sku=sku, **stock_metrics(parts))
                  for (account, day, sku), parts in stock_parts.items()]
    stock_start = client.query("SELECT minOrNull(toDate(toDateTime(toString(snapshot_ts),'UTC'),'Europe/Moscow')) FROM raw_ozon_stocks WHERE account_id IN (" + scoped + ")", parameters=params).result_rows[0][0]
    external = client.query("SELECT count() FROM dim_additional_expense FINAL WHERE organization_id=%(org)s AND month BETWEEN toStartOfMonth(toDate(%(start)s)) AND toStartOfMonth(toDate(%(stop)s)) AND amount_rub!=0", parameters=params).result_rows[0][0]
    return {"daily": daily, "stocks": stock_rows, "stock_start": str(stock_start) if stock_start else None, "advertising": advertising,
            "external": None if external else 0,
            "tax_rate": float(os.getenv('PNL_TAX_RATE_PCT', '8')) / 100 if os.getenv('PNL_REALIZATION_TAX_ENABLED','false').lower() == 'true' and auth.organization_id == os.getenv('PNL_TAX_ORGANIZATION_ID','default') else None,
            "notes": ["Выкупы и возвраты — по дате финансового события; отчёт СНГ учитывается без повторных продаж.",
                      "Цена покупателя и расходы для прогноза — оценки по финансовой истории SKU за 90 дней до периода.",
                      "Исторические остатки доступны только с начала записи снимков; общие расходы без SKU не распределяются."]}
