"""Stocks endpoints."""

from __future__ import annotations

from app.core.deps import ChClientDependency
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Query

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/current")
def stocks_current(
    *,
    marketplace: str = Query(default=""),
    account_id: str = Query(default=""),
    limit: int = Query(default=1000, ge=1, le=10000),
    client: ChClientDependency,
) -> dict[str, object]:
    service = MetricsService(client)
    items = service.stocks_current(marketplace=marketplace, account_id=account_id, limit=limit)
    return {"items": items}
