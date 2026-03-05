"""Stocks endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_ch_client
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/current")
def stocks_current(
    marketplace: str = Query(default=""),
    account_id: str = Query(default=""),
    limit: int = Query(default=1000, ge=1, le=10000),
    client=Depends(get_ch_client),
) -> dict[str, object]:
    service = MetricsService(client)
    items = service.stocks_current(marketplace=marketplace, account_id=account_id, limit=limit)
    return {"items": items}
