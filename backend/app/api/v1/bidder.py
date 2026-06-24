from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_key_or_org_role
from app.models.bidder import AdCampaign, AdRule, AdRuleCreate, AdRuleUpdate
from app.models.organization import OrgMemberRole
from app.services.bidder_service import BidderService
from fastapi import APIRouter, Depends, HTTPException, Query, status

router = APIRouter(prefix="/bidder", tags=["bidder"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> BidderService:
    return BidderService(ch)


@router.get("/campaigns")
def list_campaigns(
    ch: ChClientDependency,
    marketplace: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> list[AdCampaign]:
    return _svc(ch).list_campaigns(marketplace, account_id)


@router.post("/campaigns/sync")
def sync_campaigns(
    body: list[AdCampaign],
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> dict[str, str]:
    _svc(ch).sync_campaigns(body)
    return {"status": "ok"}


@router.get("/rules")
def list_rules(
    ch: ChClientDependency,
    marketplace: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> list[AdRule]:
    return _svc(ch).list_rules(marketplace, account_id)


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    body: AdRuleCreate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> AdRule:
    return _svc(ch).create_rule(body)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: AdRuleUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> AdRule:
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
