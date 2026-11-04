"""Funnel endpoints."""

from __future__ import annotations

import json
import math
import os
from datetime import date, timedelta
from typing import Any, Literal

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AnalyticsReadAuth, CatalogWriteAuth
from app.core.deps import ChClientDependency, QueryCacheDependency
from app.db.ch import query_dicts
from app.models.api import (
    DateRangeQueryParams,
    build_paginated_response,
    get_date_range_query_params,
)
from app.models.organization import OrgMemberRole
from app.services.metrics_service import MetricsService
from app.services.tenancy import AccountAccessError, ensure_account_access
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from common.funnel_economics import campaign_kind, finance_days, stock_metrics

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


MAX_IMPORT_PARTITIONS = 24
IMPORT_BATCH_SIZE = 5000


class OzonFunnelRow(BaseModel):
    day: date = Field(ge=date(2015, 1, 1), le=date(2100, 1, 1))
    sku: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._:-]+$")
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
    marketplace: Literal["wb", "ozon", "ym"] = "ozon"
    rows: list[OzonFunnelRow] = Field(min_length=1, max_length=25000)

    @model_validator(mode="after")
    def unique_rows(self) -> OzonFunnelImport:
        keys = [(r.day, r.sku, r.scheme) for r in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError("Повторяются строки с одинаковыми датой, SKU и схемой работы")
        partitions = {(r.day.year, r.day.month) for r in self.rows}
        if len(partitions) > MAX_IMPORT_PARTITIONS:
            n_part = len(partitions)
            msg = f"import batch spans {n_part} monthly partitions (max {MAX_IMPORT_PARTITIONS})"
            raise ValueError(msg)
        return self


def _execute_funnel_import(
    payload: OzonFunnelImport,
    auth: CatalogWriteAuth,
    client: ChClientDependency,
) -> dict[str, int]:
    mp = payload.marketplace
    try:
        ensure_account_access(client, auth.organization_id, mp, payload.account_id)
    except AccountAccessError as exc:
        detail = "Кабинет Ozon не найден" if mp == "ozon" else f"Кабинет {mp.upper()} не найден"
        raise HTTPException(status_code=404, detail=detail) from exc

    cols = [
        "account_id",
        "marketplace",
        "day",
        "sku",
        "scheme",
        "offer_id",
        "title",
        "position",
        "impressions",
        "search_impressions",
        "clicks",
        "carts",
    ]
    data = [
        [
            payload.account_id,
            mp,
            r.day,
            r.sku,
            r.scheme,
            r.offer_id,
            r.title,
            r.position,
            r.impressions,
            r.search_impressions,
            r.clicks,
            r.carts,
        ]
        for r in payload.rows
    ]
    for idx in range(0, len(data), IMPORT_BATCH_SIZE):
        client.insert(
            "raw_ozon_funnel_import",
            data[idx : idx + IMPORT_BATCH_SIZE],
            column_names=cols,
        )
    return {"imported": len(payload.rows)}


@router.post("/import")
def import_funnel(
    payload: OzonFunnelImport,
    auth: CatalogWriteAuth,
    client: ChClientDependency,
) -> dict[str, int]:
    return _execute_funnel_import(payload, auth, client)


@router.post("/ozon/import")
def import_ozon_funnel(
    payload: OzonFunnelImport,
    auth: CatalogWriteAuth,
    client: ChClientDependency,
) -> dict[str, int]:
    return _execute_funnel_import(payload, auth, client)


def _query_funnel_analytics(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams,
    default_marketplace: str = "ozon",
) -> dict[str, object]:
    mp = filters.marketplace or default_marketplace

    if mp == "ozon":
        sql = """
          SELECT day, account_id, sku, scheme, offer_id, title, position,
                 impressions, search_impressions, clicks, carts
          FROM raw_ozon_funnel_import FINAL
          WHERE marketplace = 'ozon'
          AND day BETWEEN %(date_from)s AND %(date_to)s
          AND (%(account_id)s = '' OR account_id = %(account_id)s)
          AND account_id IN (
            SELECT account_id FROM dim_account FINAL
            WHERE marketplace = 'ozon' AND organization_id = %(organization_id)s
          )
          ORDER BY day DESC, account_id ASC, sku ASC, scheme ASC
          LIMIT %(limit)s OFFSET %(offset)s
        """
        params = {
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "account_id": filters.account_id,
            "organization_id": auth.organization_id,
            "limit": filters.query_limit,
            "offset": filters.offset,
        }
    else:
        sql = """
        WITH manual AS (
          SELECT day, account_id, sku, scheme, offer_id, title, position,
                 impressions, search_impressions, clicks, carts, 1 AS priority
          FROM raw_ozon_funnel_import FINAL
          WHERE marketplace = %(marketplace)s
            AND day BETWEEN %(date_from)s AND %(date_to)s
            AND (%(account_id)s = '' OR account_id = %(account_id)s)
            AND account_id IN (
              SELECT account_id FROM dim_account FINAL
              WHERE marketplace = %(marketplace)s AND organization_id = %(organization_id)s
            )
        ), auto AS (
          SELECT
            f.day AS day,
            f.account_id AS account_id,
            f.product_id AS sku,
            'API' AS scheme,
            anyLast(p.offer_id) AS offer_id,
            anyLast(p.title) AS title,
            0.0 AS position,
            sum(f.views) AS impressions,
            0 AS search_impressions,
            sum(f.views) AS clicks,
            sum(f.adds_to_cart) AS carts,
            0 AS priority
          FROM mrt_funnel_daily AS f FINAL
          LEFT JOIN dim_product AS p FINAL
            ON f.marketplace = p.marketplace
            AND f.account_id = p.account_id
            AND f.product_id = p.product_id
          WHERE f.marketplace = %(marketplace)s
            AND f.day BETWEEN %(date_from)s AND %(date_to)s
            AND (%(account_id)s = '' OR f.account_id = %(account_id)s)
            AND f.account_id IN (
              SELECT account_id FROM dim_account FINAL
              WHERE marketplace = %(marketplace)s AND organization_id = %(organization_id)s
            )
          GROUP BY f.day, f.account_id, f.product_id
        ), combined AS (
          SELECT * FROM manual
          UNION ALL
          SELECT * FROM auto
        )
        SELECT day, account_id, sku, scheme,
               argMax(offer_id, priority) AS offer_id,
               argMax(title, priority) AS title,
               argMax(position, priority) AS position,
               argMax(impressions, priority) AS impressions,
               argMax(search_impressions, priority) AS search_impressions,
               argMax(clicks, priority) AS clicks,
               argMax(carts, priority) AS carts
        FROM combined
        GROUP BY day, account_id, sku, scheme
        ORDER BY day DESC, account_id ASC, sku ASC, scheme ASC
        LIMIT %(limit)s OFFSET %(offset)s
        """
        params = {
            "marketplace": mp,
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "account_id": filters.account_id,
            "organization_id": auth.organization_id,
            "limit": filters.query_limit,
            "offset": filters.offset,
        }

    rows = query_dicts(client, sql, params)
    return build_paginated_response(
        items=rows,
        limit=filters.limit,
        offset=filters.offset,
        **{"from": filters.date_from.isoformat(), "to": filters.date_to.isoformat()},
    )


@router.get("/analytics")
def funnel_analytics(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
) -> dict[str, object]:
    return _query_funnel_analytics(auth, client, filters, default_marketplace="ozon")


@router.get("/ozon")
def ozon_funnel(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
) -> dict[str, object]:
    return _query_funnel_analytics(auth, client, filters, default_marketplace="ozon")


def _query_funnel_related(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams,
    default_marketplace: str = "ozon",
) -> dict[str, object]:
    can_view_costs = auth.allows(OrgMemberRole.manager)
    mp = filters.marketplace or default_marketplace

    if mp == "ozon":
        cost_union = (
            """
          UNION ALL
          SELECT 'cost' AS kind, toDate(%(date_from)s) AS day, i.account_id AS account_id,
            i.sku AS sku, 0. AS qty, toFloat64(c.cost_price_rub) AS amount
          FROM (
            SELECT account_id, product_id AS sku, any(offer_id) AS offer_id
            FROM dim_product FINAL
            WHERE marketplace = 'ozon' AND account_id IN scoped
            GROUP BY account_id, product_id
          ) i INNER JOIN dim_offer_cost c FINAL
            ON c.organization_id = %(organization_id)s AND c.offer_id = i.offer_id
        """
            if can_view_costs
            else ""
        )

        sql = f"""
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
          SELECT account_id, assumeNotNull(posting_number) AS posting_number,
            assumeNotNull(product_id) AS sku, -sumIf(qty, qty < 0) AS returned
          FROM stg_sales FINAL WHERE marketplace='ozon' AND account_id IN scoped
            AND posting_number IS NOT NULL AND product_id IS NOT NULL
          GROUP BY account_id, posting_number, product_id
        ), joined AS (
          SELECT p.account_id AS account_id, p.created AS created, p.status AS status,
            i.ozon_product_id AS sku, i.quantity AS quantity, i.price AS price,
            least(toInt64(i.quantity), greatest(toInt64(ifNull(r.returned, 0)), 0)) AS returned
          FROM postings p INNER JOIN items i
            ON p.account_id = i.account_id AND p.posting_number = i.posting_number
          LEFT JOIN returns r
            ON p.account_id = r.account_id AND p.posting_number = r.posting_number
            AND toString(i.ozon_product_id) = r.sku
        )
        SELECT kind, day, account_id, sku, sum(qty) AS qty, sum(amount) AS amount FROM (
          SELECT 'orders' AS kind,
            toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') AS day,
            account_id, toString(sku) AS sku,
            toFloat64(quantity) AS qty, toFloat64(quantity * price) AS amount
          FROM joined WHERE day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'cancelled' AS kind,
            toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') AS day,
            account_id, toString(sku) AS sku, toFloat64(quantity) AS qty,
            toFloat64(quantity * price) AS amount
          FROM joined WHERE status = 'cancelled' AND day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'pending' AS kind,
            toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') AS day,
            account_id, toString(sku) AS sku, toFloat64(quantity) AS qty,
            toFloat64(quantity * price) AS amount
          FROM joined WHERE status NOT IN ('delivered', 'cancelled')
            AND day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'cohort_delivered' AS kind,
            toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') AS day,
            account_id, toString(sku) AS sku, toFloat64(quantity-returned) AS qty,
            toFloat64(quantity) AS amount
          FROM joined WHERE status='delivered' AND day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'history' AS kind, toDate(%(date_from)s) AS day, account_id, toString(sku) AS sku,
            toFloat64(if(status = 'delivered', quantity - returned, 0)) AS qty,
            toFloat64(if(status = 'cancelled', quantity, returned)) AS amount
          FROM joined
          WHERE status IN ('delivered', 'cancelled')
            AND toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') >=
                subtractDays(toDate(%(date_from)s), 90)
            AND toDate(toDateTime(toString(created), 'UTC'), 'Europe/Moscow') <
                toDate(%(date_from)s)
          {cost_union}
          UNION ALL
          SELECT 'ads' AS kind, day, account_id, toString(sku) AS sku,
                 0. AS qty, toFloat64(cost) AS amount
          FROM raw_ozon_sku_ad_reports FINAL
          WHERE account_id IN scoped AND day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'stock' AS kind, day, account_id, product_id AS sku,
            toFloat64(stock_end) AS qty, 0. AS amount
          FROM mrt_stock_daily FINAL WHERE marketplace = 'ozon' AND account_id IN scoped
            AND day BETWEEN %(date_from)s AND %(date_to)s
        ) GROUP BY kind, day, account_id, sku
        ORDER BY day, kind, account_id, sku LIMIT %(limit)s OFFSET %(offset)s
        """
        params = {
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "account_id": filters.account_id,
            "organization_id": auth.organization_id,
            "limit": filters.query_limit,
            "offset": filters.offset,
        }
    else:
        cost_union = (
            """
          UNION ALL
          SELECT 'cost' AS kind, toDate(%(date_from)s) AS day, i.account_id AS account_id,
            i.sku AS sku, 0. AS qty, toFloat64(c.cost_price_rub) AS amount
          FROM (
            SELECT account_id, toString(product_id) AS sku, any(offer_id) AS offer_id
            FROM dim_product FINAL
            WHERE marketplace = %(marketplace)s AND account_id IN scoped
            GROUP BY account_id, product_id
          ) i INNER JOIN dim_offer_cost c FINAL
            ON c.organization_id = %(organization_id)s AND c.offer_id = i.offer_id
        """
            if can_view_costs
            else ""
        )

        sql = f"""
        WITH scoped AS (
          SELECT account_id FROM dim_account FINAL
          WHERE marketplace = %(marketplace)s AND organization_id = %(organization_id)s
            AND (%(account_id)s = '' OR account_id = %(account_id)s)
        ), orders_base AS (
          SELECT
            account_id,
            order_id,
            assumeNotNull(product_id) AS sku,
            argMax(status, ingested_at) AS status,
            argMax(qty, ingested_at) AS quantity,
            argMax(price_gross, ingested_at) AS price,
            toDate(toDateTime(min(event_ts), 'UTC'), 'Europe/Moscow') AS created_day
          FROM stg_orders FINAL
          WHERE marketplace = %(marketplace)s AND account_id IN scoped AND product_id IS NOT NULL
          GROUP BY account_id, order_id, product_id
        ), returns_base AS (
          SELECT
            account_id,
            assumeNotNull(order_id) AS order_id,
            assumeNotNull(product_id) AS sku,
            -sumIf(qty, qty < 0) AS returned
          FROM stg_sales FINAL
          WHERE marketplace = %(marketplace)s AND account_id IN scoped
            AND order_id IS NOT NULL AND product_id IS NOT NULL
          GROUP BY account_id, order_id, product_id
        ), joined AS (
          SELECT
            o.account_id AS account_id,
            o.created_day AS day,
            o.sku AS sku,
            o.status AS status,
            toFloat64(ifNull(o.quantity, 0)) AS quantity,
            toFloat64(ifNull(o.price, 0)) AS price,
            least(
              toFloat64(ifNull(o.quantity, 0)),
              greatest(toFloat64(ifNull(r.returned, 0)), 0.0)
            ) AS returned
          FROM orders_base o
          LEFT JOIN returns_base r
            ON o.account_id = r.account_id AND o.order_id = r.order_id AND o.sku = r.sku
        )
        SELECT kind, day, account_id, sku, sum(qty) AS qty, sum(amount) AS amount FROM (
          SELECT 'orders' AS kind, day, account_id, sku,
            quantity AS qty, (quantity * price) AS amount
          FROM joined WHERE day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'cancelled' AS kind, day, account_id, sku,
            quantity AS qty, (quantity * price) AS amount
          FROM joined WHERE status = 'cancelled' AND day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'pending' AS kind, day, account_id, sku,
            quantity AS qty, (quantity * price) AS amount
          FROM joined WHERE status NOT IN ('delivered', 'cancelled')
            AND day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'cohort_delivered' AS kind, day, account_id, sku,
            (quantity - returned) AS qty, (quantity * price) AS amount
          FROM joined WHERE status = 'delivered' AND day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'history' AS kind, toDate(%(date_from)s) AS day, account_id, sku,
            if(status = 'delivered', quantity - returned, 0) AS qty,
            if(status = 'cancelled', quantity, returned) AS amount
          FROM joined
          WHERE status IN ('delivered', 'cancelled')
            AND day >= subtractDays(toDate(%(date_from)s), 90)
            AND day < toDate(%(date_from)s)
          {cost_union}
          UNION ALL
          SELECT 'ads' AS kind, day, account_id, toString(product_id) AS sku,
                 0. AS qty, toFloat64(cost) AS amount
          FROM mrt_ad_performance_daily FINAL
          WHERE marketplace = %(marketplace)s AND account_id IN scoped
            AND day BETWEEN %(date_from)s AND %(date_to)s
          UNION ALL
          SELECT 'stock' AS kind, day, account_id, toString(product_id) AS sku,
            toFloat64(stock_end) AS qty, 0. AS amount
          FROM mrt_stock_daily FINAL
          WHERE marketplace = %(marketplace)s AND account_id IN scoped
            AND day BETWEEN %(date_from)s AND %(date_to)s
        ) GROUP BY kind, day, account_id, sku
        ORDER BY day, kind, account_id, sku LIMIT %(limit)s OFFSET %(offset)s
        """
        params = {
            "marketplace": mp,
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "account_id": filters.account_id,
            "organization_id": auth.organization_id,
            "limit": filters.query_limit,
            "offset": filters.offset,
        }

    rows = query_dicts(client, sql, params)
    return build_paginated_response(
        items=rows,
        limit=filters.limit,
        offset=filters.offset,
        **{"from": filters.date_from.isoformat(), "to": filters.date_to.isoformat()},
    )


@router.get("/related")
def funnel_related(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
) -> dict[str, object]:
    return _query_funnel_related(auth, client, filters, default_marketplace="ozon")


@router.get("/ozon/related")
def ozon_funnel_related(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
) -> dict[str, object]:
    return _query_funnel_related(auth, client, filters, default_marketplace="ozon")


def _safe_tax_rate(auth: AnalyticsReadAuth, filters: DateRangeQueryParams) -> float | None:
    tax_account = os.getenv("PNL_TAX_ACCOUNT_ID", "default").strip() or "default"
    if filters.account_id and filters.account_id != tax_account:
        return None
    raw = os.getenv("PNL_TAX_RATE_PCT", "").strip()
    if not raw:
        return None
    try:
        rate = float(raw)
    except ValueError:
        return None
    if not math.isfinite(rate) or rate < 0.0 or rate > 100.0:
        return None
    return rate / 100.0 if rate > 1.0 else rate


def _query_funnel_finance(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams,
    default_marketplace: str = "ozon",
) -> dict[str, object]:
    can_view_finance = auth.allows(OrgMemberRole.manager)
    mp = filters.marketplace or default_marketplace

    if mp == "ozon":
        params: dict[str, Any] = {
            "org": auth.organization_id,
            "account": filters.account_id,
            "start": filters.date_from - timedelta(days=90),
            "stop": filters.date_to,
        }
        scoped = (
            "SELECT account_id FROM dim_account FINAL WHERE marketplace='ozon' "
            "AND organization_id=%(org)s AND (%(account)s='' OR account_id=%(account)s)"
        )
        finance_sql = (
            f"SELECT account_id, payload FROM raw_ozon_finance_ops FINAL "
            f"WHERE account_id IN ({scoped}) "
            f"AND source='accrual_by_day' "
            f"AND toDate(JSONExtractString(payload,'date')) BETWEEN %(start)s AND %(stop)s"
        )
        finance = client.query(finance_sql, parameters=params).result_rows
        buyouts_sql = (
            f"SELECT account_id, day, payload FROM raw_ozon_cis_buyouts FINAL "
            f"WHERE account_id IN ({scoped}) AND day BETWEEN %(start)s AND %(stop)s ORDER BY day"
        )
        buyouts = client.query(buyouts_sql, parameters=params).result_rows
        daily = finance_days(finance, buyouts)
        if not can_view_finance:
            filtered_daily = []
            for r in daily:
                if str(r.get("day", "")) >= str(filters.date_from):
                    r_copy = dict(r)
                    r_copy["revenue"] = 0.0
                    r_copy["buyer"] = 0.0
                    r_copy["mp_cost"] = 0.0
                    filtered_daily.append(r_copy)
            daily = filtered_daily

        params["start"] = filters.date_from
        metadata_sql = (
            f"SELECT account_id, campaign_id, ingested_at, payload FROM raw_ozon_campaigns FINAL "
            f"WHERE account_id IN ({scoped}) ORDER BY ingested_at"
        )
        metadata = client.query(metadata_sql, parameters=params).result_rows
        campaign_types: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
        for account, campaign, ingested_at, raw in metadata:
            info = json.loads(raw) if raw else {}
            eff_raw = str(
                info.get("effectiveFrom") or info.get("fromDate") or info.get("createdAt") or ""
            )[:10]
            eff_day = eff_raw if len(eff_raw) == 10 else str(ingested_at)[:10]
            campaign_types.setdefault((account, campaign), []).append((eff_day, info))
        ad_rows = client.query(
            f"SELECT account_id, day, sku, campaign_id, cost FROM raw_ozon_sku_ad_reports FINAL "
            f"WHERE account_id IN ({scoped}) AND day BETWEEN %(start)s AND %(stop)s",
            parameters=params,
        ).result_rows
        advertising: list[dict[str, Any]] = []
        for a, d, s, c, cost in ad_rows:
            known = [
                p for effective_day, p in campaign_types.get((a, c), []) if effective_day <= str(d)
            ]
            record = known[-1] if known else {}
            advertising.append(
                dict(
                    account_id=a,
                    day=str(d),
                    sku=str(s),
                    campaign_id=c,
                    amount=float(cost) if can_view_finance else 0.0,
                    kind=campaign_kind(record),
                    strategy=record.get("productAutopilotStrategy"),
                    placement=record.get("placement"),
                    title=record.get("title", ""),
                )
            )
        stocks_sql = f"""SELECT account_id,
          toDate(toDateTime(toString(snapshot_ts),'UTC'),'Europe/Moscow') AS day,
          toString(ozon_product_id), payload FROM raw_ozon_stocks FINAL
          WHERE account_id IN ({scoped}) AND day BETWEEN %(start)s AND %(stop)s
          AND (account_id, snapshot_ts) IN (
            SELECT account_id, max(snapshot_ts) FROM raw_ozon_stocks FINAL
            WHERE account_id IN ({scoped})
            GROUP BY account_id, toDate(toDateTime(toString(snapshot_ts),'UTC'),'Europe/Moscow'))"""
        stocks = client.query(stocks_sql, parameters=params).result_rows
        stock_parts: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for account, day, sku, raw in stocks:
            stock_parts.setdefault((account, str(day), sku), []).extend(json.loads(raw))
        stock_rows = [
            dict(account_id=account, day=day, sku=sku, **stock_metrics(parts))
            for (account, day, sku), parts in stock_parts.items()
        ]
        stock_start_res = client.query(
            f"SELECT minOrNull(toDate(toDateTime(toString(snapshot_ts),'UTC'),'Europe/Moscow')) "
            f"FROM raw_ozon_stocks WHERE account_id IN ({scoped})",
            parameters=params,
        ).result_rows
        stock_start = stock_start_res[0][0] if stock_start_res else None

    else:
        # Multi-marketplace logic for WB and YM
        params = {
            "org": auth.organization_id,
            "account": filters.account_id,
            "marketplace": mp,
            "start": filters.date_from,
            "stop": filters.date_to,
        }
        scoped = (
            "SELECT account_id FROM dim_account FINAL WHERE marketplace=%(marketplace)s "
            "AND organization_id=%(org)s AND (%(account)s='' OR account_id=%(account)s)"
        )
        fin_sql = f"""SELECT
          day, account_id,
          sales + returns AS revenue,
          sales + returns AS buyer,
          -(
            commission + acquiring + logistics + reverse_logistics
            + storage + acceptance + penalties + other
          ) AS mp_cost,
          sales AS sales_raw, returns AS returns_raw
        FROM mrt_finance_daily FINAL
        WHERE marketplace = %(marketplace)s AND account_id IN ({scoped})
          AND day BETWEEN %(start)s AND %(stop)s
        ORDER BY day ASC, account_id ASC"""
        fin_rows = client.query(fin_sql, parameters=params).named_results()
        daily = []
        for r in fin_rows:
            sales_r = float(r.get("sales_raw") or 0.0)
            daily.append(
                {
                    "day": str(r["day"]),
                    "account_id": str(r["account_id"]),
                    "revenue": float(r["revenue"]) if can_view_finance else 0.0,
                    "buyer": float(r["buyer"]) if can_view_finance else 0.0,
                    "mp_cost": float(r["mp_cost"]) if can_view_finance else 0.0,
                    "sold": 1 if sales_r > 0 else 0,
                    "returned": 0,
                }
            )

        # Advertising for WB / YM
        ad_sql = f"""SELECT
          p.account_id AS account_id,
          toString(p.day) AS day,
          toString(p.product_id) AS sku,
          p.campaign_id AS campaign_id,
          toFloat64(sum(p.cost)) AS amount,
          any(c.type) AS kind,
          any(c.title) AS title
        FROM mrt_ad_performance_daily AS p FINAL
        LEFT JOIN dim_ad_campaign AS c FINAL
          ON p.marketplace = c.marketplace
          AND p.account_id = c.account_id
          AND p.campaign_id = c.campaign_id
        WHERE p.marketplace = %(marketplace)s AND p.account_id IN ({scoped})
          AND p.day BETWEEN %(start)s AND %(stop)s
        GROUP BY p.account_id, p.day, p.product_id, p.campaign_id
        ORDER BY day ASC, account_id ASC, sku ASC"""
        ad_records = client.query(ad_sql, parameters=params).named_results()
        advertising = [
            dict(
                account_id=str(r["account_id"]),
                day=str(r["day"]),
                sku=str(r["sku"]),
                campaign_id=str(r["campaign_id"]),
                amount=float(r["amount"]) if can_view_finance else 0.0,
                kind=str(r.get("kind") or "direct"),
                title=str(r.get("title") or ""),
            )
            for r in ad_records
        ]

        # Stocks for WB / YM
        stock_sql = f"""SELECT
          account_id,
          day,
          toString(product_id) AS sku,
          sum(stock_end) AS available,
          0 AS reserved,
          sum(stock_end) AS present
        FROM mrt_stock_daily FINAL
        WHERE marketplace = %(marketplace)s AND account_id IN ({scoped})
          AND day BETWEEN %(start)s AND %(stop)s
        GROUP BY account_id, day, product_id
        ORDER BY day ASC, account_id ASC, sku ASC"""
        stk_records = client.query(stock_sql, parameters=params).named_results()
        stock_rows = [
            dict(
                account_id=str(r["account_id"]),
                day=str(r["day"]),
                sku=str(r["sku"]),
                available=int(r["available"]),
                reserved=int(r["reserved"]),
                present=int(r["present"]),
            )
            for r in stk_records
        ]
        stock_start_res = client.query(
            "SELECT minOrNull(day) FROM mrt_stock_daily FINAL "
            f"WHERE marketplace = %(marketplace)s AND account_id IN ({scoped})",
            parameters=params,
        ).result_rows
        stock_start = stock_start_res[0][0] if stock_start_res else None

    external: int | None = None
    tax_rate: float | None = None
    if can_view_finance:
        ext_sql = (
            "SELECT count() FROM dim_additional_expense FINAL WHERE organization_id=%(org)s "
            "AND month BETWEEN toStartOfMonth(toDate(%(start)s)) "
            "AND toStartOfMonth(toDate(%(stop)s)) "
            "AND amount_rub!=0"
        )
        external_res = client.query(ext_sql, parameters=params).result_rows
        external = int(external_res[0][0]) if external_res else 0
        tax_rate = _safe_tax_rate(auth, filters)

    return {
        "daily": daily,
        "stocks": stock_rows,
        "stock_start": str(stock_start) if stock_start else None,
        "advertising": advertising,
        "external": external,
        "tax_rate": tax_rate,
        "notes": [
            "Выкупы и возвраты — по дате финансового события; отчёт СНГ учитывается без повторов.",
            "Цена покупателя и расходы для прогноза — оценки по истории SKU за 90 дней.",
            "Исторические остатки доступны только с начала записи снимков.",
        ],
    }


@router.get("/finance")
def funnel_finance(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
) -> dict[str, object]:
    return _query_funnel_finance(auth, client, filters, default_marketplace="ozon")


@router.get("/ozon/finance")
def ozon_funnel_finance(
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
) -> dict[str, object]:
    return _query_funnel_finance(auth, client, filters, default_marketplace="ozon")
