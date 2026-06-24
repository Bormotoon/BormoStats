from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Brand(BaseModel):
    brand_id: str
    organization_id: str = "default"
    name: str
    description: str = ""
    logo_url: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BrandCreate(BaseModel):
    brand_id: str = Field(default="", description="leave empty for auto")
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    logo_url: str = ""


class BrandUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    logo_url: str | None = None


class Category(BaseModel):
    category_id: str
    organization_id: str = "default"
    name: str
    parent_id: str | None = None
    path: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CategoryCreate(BaseModel):
    category_id: str = Field(default="", description="leave empty for auto")
    name: str = Field(min_length=1, max_length=200)
    parent_id: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    parent_id: str | None = None


class ProductPim(BaseModel):
    organization_id: str = "default"
    marketplace: str
    account_id: str
    product_id: str
    title: str = ""
    description: str = ""
    seo_keywords: str = ""
    brand_id: str | None = None
    category_id: str | None = None
    images: list[str] = []
    updated_at: datetime | None = None


class ProductPimUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    seo_keywords: str | None = None
    brand_id: str | None = None
    category_id: str | None = None
    images: list[str] | None = None


class ProductPimBulkUpdateItem(ProductPimUpdate):
    marketplace: str
    account_id: str
    product_id: str
