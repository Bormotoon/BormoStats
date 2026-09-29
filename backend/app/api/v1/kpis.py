"""KPI endpoints."""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AnalyticsReadAuth
from app.core.deps import ChClientDependency
from app.models.api import ListQueryParams, build_paginated_response, get_list_query_params
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Depends

router = APIRouter(tags=["kpis"], responses=API_ERROR_RESPONSES)


@router.get("/kpis")
def kpis(
    *,
    auth: AnalyticsReadAuth,
    filters: ListQueryParams = Depends(get_list_query_params),
    client: ChClientDependency,
) -> dict[str, object]:
    service = MetricsService(client)
    items = service.kpis(
        organization_id=auth.organization_id,
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        limit=filters.query_limit,
        offset=filters.offset,
    )
    return build_paginated_response(items=items, limit=filters.limit, offset=filters.offset)
