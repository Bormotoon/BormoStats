"""KPI endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_ch_client
from app.services.metrics_service import MetricsService

router = APIRouter(tags=["kpis"])


@router.get("/kpis")
def kpis(
    marketplace: str = Query(default=""),
    account_id: str = Query(default=""),
    client=Depends(get_ch_client),
) -> dict[str, object]:
    service = MetricsService(client)
    items = service.kpis(marketplace=marketplace, account_id=account_id)
    return {"items": items}
