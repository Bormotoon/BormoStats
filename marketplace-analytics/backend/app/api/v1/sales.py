"""Sales endpoints."""

from __future__ import annotations

import clickhouse_connect
from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import get_ch_client
from app.models.api import (
    DateRangeQueryParams,
    build_paginated_response,
    get_date_range_query_params,
)
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/sales", tags=["sales"], responses=API_ERROR_RESPONSES)


@router.get("/daily")
def sales_daily(
    *,
    filters: DateRangeQueryParams = Depends(get_date_range_query_params),
    client: clickhouse_connect.driver.Client = Depends(get_ch_client),
) -> dict[str, object]:
    service = MetricsService(client)
    items = service.sales_daily(
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
