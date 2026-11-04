from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import ManagerAuth
from app.core.deps import ChClientDependency
from app.services.article_economics_service import ArticleEconomicsService
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/economics", tags=["economics"], responses=API_ERROR_RESPONSES)


@router.get("")
def economics(
    ch: ChClientDependency,
    auth: ManagerAuth,
    date_from: date | None = None,
    date_to: date | None = None,
    marketplace: Literal["ozon", "wb", "ym"] | None = Query(default=None),
    account_id: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    stop = date_to or datetime.now(ZoneInfo("Europe/Moscow")).date()
    start = date_from or stop - timedelta(days=29)
    if start > stop or (stop - start).days > 730:
        raise HTTPException(status_code=422, detail="Выберите корректный период не более 730 дней")
    return ArticleEconomicsService(ch, auth.organization_id).build(
        start, stop, account_id=account_id, marketplace=marketplace
    )
