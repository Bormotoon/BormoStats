from __future__ import annotations

from typing import Annotated

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AdminAuth, AuthContext, MarketplaceExecuteAuth, ViewerAuth
from app.core.deps import ChClientDependency, SettingsDependency
from app.models.integrations import (
    MAX_STOCK_UPDATE_ITEMS,
    StockUpdateItem,
    StockUpdateResult,
    WebhookLog,
    WebhookSubscription,
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
    WebhookSubscriptionWithSecret,
    WebhookTestResult,
)
from app.services.integrations_service import IntegrationsService
from fastapi import APIRouter, Body, HTTPException, Query, status

from common.webhooks import EVENT_TYPES, WILDCARD_EVENT

router = APIRouter(prefix="/integrations", tags=["integrations"], responses=API_ERROR_RESPONSES)


def _svc(
    ch: ChClientDependency, settings: SettingsDependency, auth: AuthContext
) -> IntegrationsService:
    return IntegrationsService(ch, settings, auth.organization_id)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")


@router.post("/stock/update")
def stock_update(
    body: Annotated[list[StockUpdateItem], Body(min_length=1, max_length=MAX_STOCK_UPDATE_ITEMS)],
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: MarketplaceExecuteAuth,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
) -> list[StockUpdateResult]:
    return _svc(ch, settings, auth).push_stock(body, marketplace)


@router.get("/events")
def list_event_types(auth: ViewerAuth) -> list[str]:
    return [WILDCARD_EVENT, *sorted(EVENT_TYPES)]


@router.get("/subscriptions")
def list_subscriptions(
    ch: ChClientDependency, settings: SettingsDependency, auth: ViewerAuth
) -> list[WebhookSubscription]:
    return _svc(ch, settings, auth).list_subscriptions()


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def create_subscription(
    body: WebhookSubscriptionCreate,
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: AdminAuth,
) -> WebhookSubscriptionWithSecret:
    """Create a subscription. The signing secret is returned only in this response."""
    return _svc(ch, settings, auth).create_subscription(body)


@router.patch("/subscriptions/{subscription_id}")
def update_subscription(
    subscription_id: str,
    body: WebhookSubscriptionUpdate,
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: AdminAuth,
) -> WebhookSubscription:
    sub = _svc(ch, settings, auth).update_subscription(subscription_id, body)
    if sub is None:
        raise _not_found()
    return sub


@router.post("/subscriptions/{subscription_id}/rotate-secret")
def rotate_secret(
    subscription_id: str,
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: AdminAuth,
) -> WebhookSubscriptionWithSecret:
    sub = _svc(ch, settings, auth).rotate_secret(subscription_id)
    if sub is None:
        raise _not_found()
    return sub


@router.post("/subscriptions/{subscription_id}/test", status_code=status.HTTP_202_ACCEPTED)
def test_subscription(
    subscription_id: str,
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: AdminAuth,
) -> WebhookTestResult:
    event_id = _svc(ch, settings, auth).send_test(subscription_id)
    if event_id is None:
        raise _not_found()
    return WebhookTestResult(event_id=event_id, queued=True)


@router.delete("/subscriptions/{subscription_id}")
def delete_subscription(
    subscription_id: str,
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: AdminAuth,
) -> dict[str, bool]:
    if not _svc(ch, settings, auth).delete_subscription(subscription_id):
        raise _not_found()
    return {"ok": True}


@router.get("/logs")
def list_logs(
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: AdminAuth,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[WebhookLog]:
    return _svc(ch, settings, auth).list_logs(limit)
