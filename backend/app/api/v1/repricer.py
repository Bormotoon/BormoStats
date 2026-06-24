from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_key_or_org_role
from app.models.organization import OrgMemberRole
from app.models.repricer import BreakevenRow, PriceRule, PriceRuleCreate, PriceRuleUpdate
from app.services.repricer_service import RepricerService
from fastapi import APIRouter, Depends, HTTPException, Query, status

router = APIRouter(prefix="/repricer", tags=["repricer"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> RepricerService:
    return RepricerService(ch)


@router.get("/rules")
def list_rules(
    ch: ChClientDependency,
    marketplace: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> list[PriceRule]:
    return _svc(ch).list_rules(marketplace, account_id)


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    body: PriceRuleCreate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> PriceRule:
    return _svc(ch).create_rule(body)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: PriceRuleUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> PriceRule:
    rule = _svc(ch).update_rule(rule_id, body)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> dict[str, bool]:
    ok = _svc(ch).delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    return {"deleted": True}


@router.get("/breakeven")
def list_breakeven(
    ch: ChClientDependency,
    marketplace: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> list[BreakevenRow]:
    return _svc(ch).get_breakeven(marketplace, account_id)
