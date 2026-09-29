from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AdminAuth, AuthContext, ManagerAuth, Scope, ensure_scope
from app.core.deps import ChClientDependency
from app.models.bidder import AdCampaign, AdRule, AdRuleCreate, AdRuleUpdate
from app.models.marketplace_actions import MarketplaceAction
from app.services.bidder_service import BidderService
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/bidder", tags=["bidder"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency, auth: AuthContext) -> BidderService:
    return BidderService(ch, auth.organization_id)


@router.get("/campaigns")
def list_campaigns(
    ch: ChClientDependency,
    auth: ManagerAuth,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    account_id: str | None = Query(default=None, max_length=64),
) -> list[AdCampaign]:
    return _svc(ch, auth).list_campaigns(marketplace, account_id)


@router.post("/campaigns/sync")
def sync_campaigns(
    body: list[AdCampaign],
    ch: ChClientDependency,
    auth: AdminAuth,
) -> dict[str, object]:
    return {"status": "ok", "synced": _svc(ch, auth).sync_campaigns(body)}


@router.get("/rules")
def list_rules(
    ch: ChClientDependency,
    auth: ManagerAuth,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    account_id: str | None = Query(default=None, max_length=64),
) -> list[AdRule]:
    return _svc(ch, auth).list_rules(marketplace, account_id)


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    body: AdRuleCreate,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> AdRule:
    if body.dry_run is False:
        ensure_scope(auth, Scope.execute_marketplace, "disable dry-run")
    return _svc(ch, auth).create_rule(body)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: AdRuleUpdate,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> AdRule:
    if body.dry_run is False:
        ensure_scope(auth, Scope.execute_marketplace, "disable dry-run")
    rule = _svc(ch, auth).update_rule(rule_id, body)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> dict[str, bool]:
    ok = _svc(ch, auth).delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    return {"deleted": True}


@router.get("/actions")
def list_actions(
    ch: ChClientDependency,
    auth: ManagerAuth,
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[MarketplaceAction]:
    """Audit trail of simulated and executed bid changes (before/after, status)."""
    return _svc(ch, auth).list_actions(limit)
