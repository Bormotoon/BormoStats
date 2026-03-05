"""Ads endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_ch_client
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/ads", tags=["ads"])


@router.get("/daily")
def ads_daily(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    marketplace: str = Query(default=""),
    account_id: str = Query(default=""),
    limit: int = Query(default=1000, ge=1, le=10000),
    client=Depends(get_ch_client),
) -> dict[str, object]:
    resolved_to = date_to or datetime.now(UTC).date()
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    service = MetricsService(client)
    items = service.ads_daily(
        date_from=resolved_from,
        date_to=resolved_to,
        marketplace=marketplace,
        account_id=account_id,
        limit=limit,
    )
    return {"items": items, "from": resolved_from.isoformat(), "to": resolved_to.isoformat()}
