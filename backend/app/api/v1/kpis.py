"""KPI endpoints."""

from __future__ import annotations

import clickhouse_connect
from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import get_ch_client
from app.models.api import ListQueryParams, build_paginated_response, get_list_query_params
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Depends

router = APIRouter(tags=["kpis"], responses=API_ERROR_RESPONSES)


@router.get("/kpis")
def kpis(
    *,
    filters: ListQueryParams = Depends(get_list_query_params),
    client: clickhouse_connect.driver.Client = Depends(get_ch_client),
) -> dict[str, object]:
    service = MetricsService(client)
    items = service.kpis(
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        limit=filters.query_limit,
        offset=filters.offset,
    )
    return build_paginated_response(items=items, limit=filters.limit, offset=filters.offset)
