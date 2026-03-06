"""Funnel endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.core.deps import ChClientDependency
from app.services.metrics_service import MetricsService
from fastapi import APIRouter, Query

router = APIRouter(prefix="/funnel", tags=["funnel"])


@router.get("/daily")
def funnel_daily(
    *,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    marketplace: str = Query(default=""),
    account_id: str = Query(default=""),
    limit: int = Query(default=1000, ge=1, le=10000),
    client: ChClientDependency,
) -> dict[str, object]:
    resolved_to = date_to or datetime.now(UTC).date()
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    service = MetricsService(client)
    items = service.funnel_daily(
        date_from=resolved_from,
        date_to=resolved_to,
        marketplace=marketplace,
        account_id=account_id,
        limit=limit,
    )
    return {"items": items, "from": resolved_from.isoformat(), "to": resolved_to.isoformat()}
