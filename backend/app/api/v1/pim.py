from __future__ import annotations

from typing import Any

from app.api.errors import API_ERROR_RESPONSES
from app.core.config import get_settings
from app.core.deps import ChClientDependency, CurrentUserDependency, require_admin_key_or_org_role
from app.models.organization import OrgMemberRole
from app.models.pim import (
    Brand,
    BrandCreate,
    BrandUpdate,
    Category,
    CategoryCreate,
    CategoryUpdate,
    ProductPim,
    ProductPimBulkUpdateItem,
    ProductPimUpdate,
)
from app.services.ai_service import AiService
from app.services.pim_service import PimService
from fastapi import APIRouter, Depends, HTTPException, Query, status

router = APIRouter(prefix="/pim", tags=["pim"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> PimService:
    return PimService(ch)


# -- Brands -----------------------------------------------------------------------


@router.get("/brands")
def list_brands(
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.viewer)),
) -> list[Brand]:
    return _svc(ch).list_brands("default")


@router.post("/brands", status_code=status.HTTP_201_CREATED)
def create_brand(
    body: BrandCreate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> Brand:
    return _svc(ch).create_brand(body)


@router.patch("/brands/{brand_id}")
def update_brand(
    brand_id: str,
    body: BrandUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> Brand:
    brand = _svc(ch).update_brand(brand_id, body)
    if brand is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="brand not found")
    return brand


@router.delete("/brands/{brand_id}")
def delete_brand(
    brand_id: str,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> dict[str, bool]:
    deleted = _svc(ch).delete_brand(brand_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="brand not found")
    return {"ok": True}


# -- Categories -------------------------------------------------------------------


@router.get("/categories")
def list_categories(
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.viewer)),
) -> list[Category]:
    return _svc(ch).list_categories("default")


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryCreate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> Category:
    return _svc(ch).create_category(body)


@router.patch("/categories/{category_id}")
def update_category(
    category_id: str,
    body: CategoryUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> Category:
    cat = _svc(ch).update_category(category_id, body)
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category not found")
    return cat


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: str,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> dict[str, bool]:
    deleted = _svc(ch).delete_category(category_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category not found")
    return {"ok": True}


# -- Products ---------------------------------------------------------------------


@router.get("/products")
def list_products(
    ch: ChClientDependency,
    current_user: CurrentUserDependency,
    marketplace: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="search in title or product_id"),
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.viewer)),
) -> list[ProductPim]:
    return _svc(ch).list_products(
        organization_id=current_user.organization_id,
        marketplace=marketplace,
        account_id=account_id,
        q=q,
    )


@router.patch("/products/{marketplace}/{account_id}/{product_id}")
def update_product(
    marketplace: str,
    account_id: str,
    product_id: str,
    body: ProductPimUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> ProductPim:
    prod = _svc(ch).update_product(marketplace, account_id, product_id, body)
    if prod is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="product not found")
    return prod


@router.post("/products/generate-description")
def generate_description(
    body: ProductPimUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> dict[str, str]:
    s = get_settings()
    ai = AiService(s.ai_api_url, s.ai_api_key, s.ai_model)
    desc = ai.generate_description(
        name=body.title or "",
        brand=body.brand_id or "",
        category=body.category_id or "",
    )
    if desc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service not available. Configure AI_API_URL and AI_API_KEY",
        )
    return {"description": desc}


@router.post("/products/bulk-update")
def bulk_update_products(
    body: list[ProductPimBulkUpdateItem],
    ch: ChClientDependency,
    current_user: CurrentUserDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> dict[str, int]:
    count = _svc(ch).bulk_update_products(current_user.organization_id, body)
    return {"updated": count}
