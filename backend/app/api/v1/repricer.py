from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AdminAuth, AuthContext, ManagerAuth, Scope, ensure_scope
from app.core.deps import ChClientDependency
from app.models.marketplace_actions import MarketplaceAction
from app.models.repricer import BreakevenRow, PriceRule, PriceRuleCreate, PriceRuleUpdate
from app.services.repricer_service import RepricerService
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/repricer", tags=["repricer"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency, auth: AuthContext) -> RepricerService:
    return RepricerService(ch, auth.organization_id)


@router.get("/rules")
def list_rules(
    ch: ChClientDependency,
    auth: ManagerAuth,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    account_id: str | None = Query(default=None, max_length=64),
) -> list[PriceRule]:
    return _svc(ch, auth).list_rules(marketplace, account_id)


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    body: PriceRuleCreate,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> PriceRule:
    if body.dry_run is False:
        ensure_scope(auth, Scope.execute_marketplace, "disable dry-run")
    return _svc(ch, auth).create_rule(body)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: PriceRuleUpdate,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> PriceRule:
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


@router.get("/breakeven")
def list_breakeven(
    ch: ChClientDependency,
    auth: ManagerAuth,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    account_id: str | None = Query(default=None, max_length=64),
) -> list[BreakevenRow]:
    return _svc(ch, auth).get_breakeven(marketplace, account_id)


@router.get("/actions")
def list_actions(
    ch: ChClientDependency,
    auth: ManagerAuth,
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[MarketplaceAction]:
    """Audit trail of simulated and executed price changes (before/after, status)."""
    return _svc(ch, auth).list_actions(limit)
