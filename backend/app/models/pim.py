from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

ID_PATTERN = r"^[A-Za-z0-9._:-]*$"
MAX_BULK_UPDATE_ITEMS = 500


class Brand(BaseModel):
    brand_id: str
    organization_id: str = "default"
    name: str
    description: str = ""
    logo_url: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BrandCreate(BaseModel):
    brand_id: str = Field(
        default="", max_length=64, pattern=ID_PATTERN, description="leave empty for auto"
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    logo_url: str = Field(default="", max_length=2048)


class BrandUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    logo_url: str | None = Field(default=None, max_length=2048)


class Category(BaseModel):
    category_id: str
    organization_id: str = "default"
    name: str
    parent_id: str | None = None
    path: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CategoryCreate(BaseModel):
    category_id: str = Field(
        default="", max_length=64, pattern=ID_PATTERN, description="leave empty for auto"
    )
    name: str = Field(min_length=1, max_length=200)
    parent_id: str | None = Field(default=None, max_length=64)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: str | None = Field(default=None, max_length=64)


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
    title: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=20000)
    seo_keywords: str | None = Field(default=None, max_length=5000)
    brand_id: str | None = Field(default=None, max_length=64)
    category_id: str | None = Field(default=None, max_length=64)
    images: list[str] | None = Field(default=None, max_length=50)


class ProductPimBulkUpdateItem(ProductPimUpdate):
    marketplace: str = Field(pattern=r"^(wb|ozon)$")
    account_id: str = Field(min_length=1, max_length=64)
    product_id: str = Field(min_length=1, max_length=64)
