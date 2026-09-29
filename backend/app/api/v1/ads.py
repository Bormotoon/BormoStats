"""Ads endpoints."""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AnalyticsReadAuth
from app.core.deps import ChClientDependency
from app.models.api import (
    DateRangeQueryParams,
    build_paginated_response,
    get_date_range_query_params,
)
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/ads", tags=["ads"], responses=API_ERROR_RESPONSES)


@router.get("/daily")
def ads_daily(
    *,
    auth: AnalyticsReadAuth,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
    client: ChClientDependency,
) -> dict[str, object]:
    service = MetricsService(client)
    items = service.ads_daily(
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
