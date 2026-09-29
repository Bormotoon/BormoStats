from __future__ import annotations

from typing import Annotated

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AdminAuth, AuthContext, CatalogWriteAuth, ViewerAuth
from app.core.deps import ChClientDependency, SettingsDependency
from app.models.pim import (
    MAX_BULK_UPDATE_ITEMS,
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
from fastapi import APIRouter, Body, HTTPException, Query, status

router = APIRouter(prefix="/pim", tags=["pim"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency, auth: AuthContext) -> PimService:
    return PimService(ch, auth.organization_id)


# -- Brands -----------------------------------------------------------------------


@router.get("/brands")
def list_brands(ch: ChClientDependency, auth: ViewerAuth) -> list[Brand]:
    return _svc(ch, auth).list_brands()


@router.post("/brands", status_code=status.HTTP_201_CREATED)
def create_brand(body: BrandCreate, ch: ChClientDependency, auth: CatalogWriteAuth) -> Brand:
    return _svc(ch, auth).create_brand(body)


@router.patch("/brands/{brand_id}")
def update_brand(
    brand_id: str,
    body: BrandUpdate,
    ch: ChClientDependency,
    auth: CatalogWriteAuth,
) -> Brand:
    brand = _svc(ch, auth).update_brand(brand_id, body)
    if brand is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="brand not found")
    return brand


@router.delete("/brands/{brand_id}")
def delete_brand(brand_id: str, ch: ChClientDependency, auth: AdminAuth) -> dict[str, bool]:
    if not _svc(ch, auth).delete_brand(brand_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="brand not found")
    return {"ok": True}


# -- Categories -------------------------------------------------------------------


@router.get("/categories")
def list_categories(ch: ChClientDependency, auth: ViewerAuth) -> list[Category]:
    return _svc(ch, auth).list_categories()


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryCreate, ch: ChClientDependency, auth: CatalogWriteAuth
) -> Category:
    return _svc(ch, auth).create_category(body)


@router.patch("/categories/{category_id}")
def update_category(
    category_id: str,
    body: CategoryUpdate,
    ch: ChClientDependency,
    auth: CatalogWriteAuth,
) -> Category:
    cat = _svc(ch, auth).update_category(category_id, body)
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category not found")
    return cat


@router.delete("/categories/{category_id}")
def delete_category(category_id: str, ch: ChClientDependency, auth: AdminAuth) -> dict[str, bool]:
    if not _svc(ch, auth).delete_category(category_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category not found")
    return {"ok": True}


# -- Products ---------------------------------------------------------------------


@router.get("/products")
def list_products(
    ch: ChClientDependency,
    auth: ViewerAuth,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    account_id: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=200, description="title substring or id"),
) -> list[ProductPim]:
    return _svc(ch, auth).list_products(marketplace=marketplace, account_id=account_id, q=q)


@router.patch("/products/{marketplace}/{account_id}/{product_id}")
def update_product(
    marketplace: str,
    account_id: str,
    product_id: str,
    body: ProductPimUpdate,
    ch: ChClientDependency,
    auth: CatalogWriteAuth,
) -> ProductPim:
    prod = _svc(ch, auth).update_product(marketplace, account_id, product_id, body)
    if prod is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="product not found")
    return prod


@router.post("/products/generate-description")
def generate_description(
    body: ProductPimUpdate,
    auth: CatalogWriteAuth,
    settings: SettingsDependency,
) -> dict[str, str]:
    ai = AiService(settings.ai_api_url, settings.ai_api_key, settings.ai_model)
    try:
        desc = ai.generate_description(
            name=body.title or "",
            brand=body.brand_id or "",
            category=body.category_id or "",
        )
    finally:
        ai.close()
    if desc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service not available. Configure AI_API_URL and AI_API_KEY",
        )
    return {"description": desc}


@router.post("/products/bulk-update")
def bulk_update_products(
    body: Annotated[list[ProductPimBulkUpdateItem], Body(max_length=MAX_BULK_UPDATE_ITEMS)],
    ch: ChClientDependency,
    auth: CatalogWriteAuth,
) -> dict[str, int]:
    return {"updated": _svc(ch, auth).bulk_update_products(body)}
