"""KPI endpoints."""

from __future__ import annotations

from app.core.deps import ChClientDependency
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Query

router = APIRouter(tags=["kpis"])


@router.get("/kpis")
def kpis(
    *,
    marketplace: str = Query(default=""),
    account_id: str = Query(default=""),
    client: ChClientDependency,
) -> dict[str, object]:
    service = MetricsService(client)
    items = service.kpis(marketplace=marketplace, account_id=account_id)
    return {"items": items}
