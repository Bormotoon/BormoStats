"""Stocks endpoints."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AnalyticsReadAuth
from app.core.deps import ChClientDependency, QueryCacheDependency
from app.models.api import ListQueryParams, build_paginated_response, get_list_query_params
from app.models.organization import OrgMemberRole
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/stocks", tags=["stocks"], responses=API_ERROR_RESPONSES)


@router.get("/current")
def stocks_current(
    *,
    auth: AnalyticsReadAuth,
    filters: ListQueryParams = Depends(get_list_query_params),
    as_of: date | None = Query(default=None),
    client: ChClientDependency,
    cache: QueryCacheDependency,
) -> dict[str, object]:
    resolved_as_of = as_of or datetime.now(ZoneInfo("Europe/Moscow")).date()
    service = MetricsService(client, cache)
    items = service.stocks_current(
        organization_id=auth.organization_id,
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        as_of=resolved_as_of,
        limit=filters.query_limit,
        offset=filters.offset,
    )
    if not auth.allows(OrgMemberRole.manager):
        items = [{**row, "cost_price_rub": None, "stock_value_rub": None} for row in items]
    return build_paginated_response(
        items=items,
        limit=filters.limit,
        offset=filters.offset,
        as_of=resolved_as_of.isoformat(),
    )
