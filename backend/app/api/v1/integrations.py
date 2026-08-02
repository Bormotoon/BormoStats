from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.config import get_settings
from app.core.deps import ChClientDependency, require_admin_key_or_org_role
from app.models.integrations import (
    StockUpdateItem,
    StockUpdateResult,
    WebhookLog,
    WebhookSubscription,
    WebhookSubscriptionCreate,
)
from app.models.organization import OrgMemberRole
from app.services.integrations_service import IntegrationsService
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/integrations", tags=["integrations"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> IntegrationsService:
    s = get_settings()
    return IntegrationsService(
        ch,
        wb_token=s.wb_statistics_token,
        ozon_client_id=s.ozon_client_id,
        ozon_api_key=s.ozon_api_key,
    )


@router.post("/stock/update")
def stock_update(
    body: list[StockUpdateItem],
    ch: ChClientDependency,
    marketplace: str | None = Query(default=None),
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> list[StockUpdateResult]:
    return _svc(ch).push_stock(body, marketplace)


@router.get("/subscriptions")
def list_subscriptions(
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.viewer)),
) -> list[WebhookSubscription]:
    return _svc(ch).list_subscriptions("default")


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def create_subscription(
    body: WebhookSubscriptionCreate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> WebhookSubscription:
    return _svc(ch).create_subscription(body)


@router.delete("/subscriptions/{subscription_id}")
def delete_subscription(
    subscription_id: str,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> dict[str, bool]:
    _svc(ch).delete_subscription(subscription_id)
    return {"ok": True}


@router.get("/logs")
def list_logs(
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> list[WebhookLog]:
    return _svc(ch).list_logs("default")
