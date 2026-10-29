from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from typing import Literal
from fastapi import APIRouter, Query, HTTPException
from app.core.auth import ManagerAuth
from app.core.deps import ChClientDependency
from app.services.article_economics_service import ArticleEconomicsService

router = APIRouter(prefix='/economics', tags=['economics'])


@router.get('')
def economics(ch: ChClientDependency, auth: ManagerAuth,
              date_from: date | None = None, date_to: date | None = None,
              marketplace: Literal['ozon','wb'] | None = Query(default=None),
              account_id: str | None = Query(default=None,max_length=64)) -> dict:
    stop=date_to or datetime.now(ZoneInfo('Europe/Moscow')).date()
    start=date_from or stop-timedelta(days=29)
    if start>stop or (stop-start).days>730:
        raise HTTPException(status_code=422,detail='Выберите корректный период не более 730 дней')
    if marketplace and marketplace != 'ozon':
        return {'items':[], 'total':None, 'notes':['Экономика по этому образцу настроена для Ozon.']}
    return ArticleEconomicsService(ch, auth.organization_id).build(start,stop,account_id)
