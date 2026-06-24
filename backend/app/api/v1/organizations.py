from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_api_key
from app.models.organization import (
    Organization,
    OrganizationCreate,
    OrganizationMember,
    OrganizationMemberCreate,
    OrganizationMemberUpdate,
    OrganizationUpdate,
    ShopAccount,
    ShopAccountCreate,
    ShopAccountUpdate,
)
from app.services.organization_service import OrganizationService
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/organizations", tags=["organizations"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> OrganizationService:
    return OrganizationService(ch)


@router.get("")
def list_organizations(
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> list[Organization]:
    return _svc(ch).list_organizations()


@router.get("/{org_id}")
def get_organization(
    org_id: str,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> Organization:
    org = _svc(ch).get_organization(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    return org


@router.post("", status_code=status.HTTP_201_CREATED)
def create_organization(
    body: OrganizationCreate,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> Organization:
    return _svc(ch).create_organization(body)


@router.patch("/{org_id}")
def update_organization(
    org_id: str,
    body: OrganizationUpdate,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> Organization:
    org = _svc(ch).update_organization(org_id, body)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    return org


@router.delete("/{org_id}")
def delete_organization(
    org_id: str,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> dict[str, bool]:
    ok = _svc(ch).delete_organization(org_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    return {"deleted": True}


# Organization Members
@router.get("/{org_id}/members")
def list_members(
    org_id: str,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> list[OrganizationMember]:
    return _svc(ch).list_members(org_id)


@router.post("/{org_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    org_id: str,
    body: OrganizationMemberCreate,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> OrganizationMember:
    return _svc(ch).add_member(org_id, body)


@router.patch("/{org_id}/members/{user_id}")
def update_member(
    org_id: str,
    user_id: str,
    body: OrganizationMemberUpdate,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> OrganizationMember:
    member = _svc(ch).update_member(org_id, user_id, body)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    return member


@router.delete("/{org_id}/members/{user_id}")
def remove_member(
    org_id: str,
    user_id: str,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> dict[str, bool]:
    ok = _svc(ch).remove_member(org_id, user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    return {"deleted": True}


# Shop Accounts (scoped to org)
@router.get("/{org_id}/accounts")
def list_shop_accounts(
    org_id: str,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> list[ShopAccount]:
    return _svc(ch).list_shop_accounts(organization_id=org_id)


@router.post("/{org_id}/accounts", status_code=status.HTTP_201_CREATED)
def create_shop_account(
    org_id: str,
    body: ShopAccountCreate,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> ShopAccount:
    return _svc(ch).create_shop_account(body, organization_id=org_id)


@router.patch("/{org_id}/accounts/{marketplace}/{account_id}")
def update_shop_account(
    org_id: str,
    marketplace: str,
    account_id: str,
    body: ShopAccountUpdate,
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> ShopAccount:
    acct = _svc(ch).update_shop_account(account_id, marketplace, body)
    if acct is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="shop account not found")
    return acct


# Global account listing (all orgs)
@router.get("/accounts/all")
def list_all_shop_accounts(
    ch: ChClientDependency,
    _admin: None = Depends(require_admin_api_key),
) -> list[ShopAccount]:
    return _svc(ch).list_shop_accounts()
