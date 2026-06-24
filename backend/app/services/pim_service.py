from __future__ import annotations

import uuid
from datetime import datetime

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
from clickhouse_connect.driver import Client


class PimService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    # -- Brands -------------------------------------------------------------------

    def list_brands(self, organization_id: str) -> list[Brand]:
        rows = self._ch.query(
            "SELECT brand_id, organization_id, name, description, logo_url, created_at, updated_at"
            " FROM dim_brand FINAL WHERE organization_id = {oid:String} ORDER BY name",
            parameters={"oid": organization_id},
        )
        return [Brand(**r) for r in rows.named_results()]

    def get_brand(self, brand_id: str) -> Brand | None:
        rows = self._ch.query(
            "SELECT brand_id, organization_id, name, description, logo_url, created_at, updated_at"
            " FROM dim_brand FINAL WHERE brand_id = {bid:String}",
            parameters={"bid": brand_id},
        )
        for r in rows.named_results():
            return Brand(**r)
        return None

    def create_brand(self, data: BrandCreate) -> Brand:
        brand_id = data.brand_id or str(uuid.uuid4())[:12]
        now = datetime.utcnow()
        self._ch.command(
            "INSERT INTO dim_brand (brand_id, organization_id, name, description, logo_url, created_at, updated_at)"
            " VALUES ({bid:String}, {oid:String}, {name:String}, {desc:String}, {logo:String}, {created:DateTime}, {updated:DateTime})",
            parameters={
                "bid": brand_id,
                "oid": "default",
                "name": data.name,
                "desc": data.description,
                "logo": data.logo_url,
                "created": now,
                "updated": now,
            },
        )
        return Brand(brand_id=brand_id, organization_id="default", name=data.name, description=data.description, logo_url=data.logo_url, created_at=now, updated_at=now)

    def update_brand(self, brand_id: str, data: BrandUpdate) -> Brand | None:
        existing = self.get_brand(brand_id)
        if not existing:
            return None
        now = datetime.utcnow()
        self._ch.command(
            "INSERT INTO dim_brand (brand_id, organization_id, name, description, logo_url, created_at, updated_at)"
            " VALUES ({bid:String}, {oid:String}, {name:String}, {desc:String}, {logo:String}, {created:DateTime}, {updated:DateTime})",
            parameters={
                "bid": brand_id,
                "oid": existing.organization_id,
                "name": data.name or existing.name,
                "desc": data.description if data.description is not None else existing.description,
                "logo": data.logo_url if data.logo_url is not None else existing.logo_url,
                "created": existing.created_at or now,
                "updated": now,
            },
        )
        return self.get_brand(brand_id)

    def delete_brand(self, brand_id: str) -> bool:
        existing = self.get_brand(brand_id)
        if not existing:
            return False
        self._ch.command(
            "ALTER TABLE dim_brand DELETE WHERE brand_id = {bid:String}",
            parameters={"bid": brand_id},
        )
        return True

    # -- Categories ---------------------------------------------------------------

    def list_categories(self, organization_id: str) -> list[Category]:
        rows = self._ch.query(
            "SELECT category_id, organization_id, name, parent_id, path, created_at, updated_at"
            " FROM dim_category FINAL WHERE organization_id = {oid:String} ORDER BY name",
            parameters={"oid": organization_id},
        )
        return [Category(**r) for r in rows.named_results()]

    def get_category(self, category_id: str) -> Category | None:
        rows = self._ch.query(
            "SELECT category_id, organization_id, name, parent_id, path, created_at, updated_at"
            " FROM dim_category FINAL WHERE category_id = {cid:String}",
            parameters={"cid": category_id},
        )
        for r in rows.named_results():
            return Category(**r)
        return None

    def create_category(self, data: CategoryCreate) -> Category:
        category_id = data.category_id or str(uuid.uuid4())[:12]
        now = datetime.utcnow()
        path = data.name
        if data.parent_id:
            parent = self.get_category(data.parent_id)
            if parent:
                path = f"{parent.path}/{data.name}"
        self._ch.command(
            "INSERT INTO dim_category (category_id, organization_id, name, parent_id, path, created_at, updated_at)"
            " VALUES ({cid:String}, {oid:String}, {name:String}, {pid:Nullable(String)}, {path:String}, {created:DateTime}, {updated:DateTime})",
            parameters={
                "cid": category_id,
                "oid": "default",
                "name": data.name,
                "pid": data.parent_id,
                "path": path,
                "created": now,
                "updated": now,
            },
        )
        return Category(category_id=category_id, organization_id="default", name=data.name, parent_id=data.parent_id, path=path, created_at=now, updated_at=now)

    def update_category(self, category_id: str, data: CategoryUpdate) -> Category | None:
        existing = self.get_category(category_id)
        if not existing:
            return None
        now = datetime.utcnow()
        name = data.name or existing.name
        parent_id = data.parent_id if data.parent_id is not None else existing.parent_id
        path = name
        if parent_id:
            parent = self.get_category(parent_id)
            if parent:
                path = f"{parent.path}/{name}"
        self._ch.command(
            "INSERT INTO dim_category (category_id, organization_id, name, parent_id, path, created_at, updated_at)"
            " VALUES ({cid:String}, {oid:String}, {name:String}, {pid:Nullable(String)}, {path:String}, {created:DateTime}, {updated:DateTime})",
            parameters={
                "cid": category_id,
                "oid": existing.organization_id,
                "name": name,
                "pid": parent_id,
                "path": path,
                "created": existing.created_at or now,
                "updated": now,
            },
        )
        return self.get_category(category_id)

    def delete_category(self, category_id: str) -> bool:
        existing = self.get_category(category_id)
        if not existing:
            return False
        self._ch.command(
            "ALTER TABLE dim_category DELETE WHERE category_id = {cid:String}",
            parameters={"cid": category_id},
        )
        return True

    # -- Product PIM --------------------------------------------------------------

    def list_products(
        self, organization_id: str, marketplace: str | None = None, account_id: str | None = None, q: str | None = None
    ) -> list[ProductPim]:
        where = ["pim.organization_id = {oid:String}"]
        params: dict[str, object] = {"oid": organization_id}
        if marketplace:
            where.append("pim.marketplace = {mp:String}")
            params["mp"] = marketplace
        if account_id:
            where.append("pim.account_id = {aid:String}")
            params["aid"] = account_id
        if q:
            where.append("(pim.title ILIKE {q:String} OR p.product_id ILIKE {q2:String})")
            params["q"] = f"%{q}%"
            params["q2"] = f"%{q}%"
        clause = " AND ".join(where)
        rows = self._ch.query(
            "SELECT pim.organization_id, pim.marketplace, pim.account_id, pim.product_id,"
            " pim.title, pim.description, pim.seo_keywords, pim.brand_id, pim.category_id,"
            " pim.images, pim.updated_at"
            " FROM dim_product_pim FINAL pim"
            f" WHERE {clause}"
            " ORDER BY pim.updated_at DESC"
            " LIMIT 500",
            parameters=params,
        )
        return [ProductPim(**r) for r in rows.named_results()]

    def get_product(self, marketplace: str, account_id: str, product_id: str) -> ProductPim | None:
        rows = self._ch.query(
            "SELECT organization_id, marketplace, account_id, product_id, title, description,"
            " seo_keywords, brand_id, category_id, images, updated_at"
            " FROM dim_product_pim FINAL"
            " WHERE marketplace = {mp:String} AND account_id = {aid:String} AND product_id = {pid:String}",
            parameters={"mp": marketplace, "aid": account_id, "pid": product_id},
        )
        for r in rows.named_results():
            return ProductPim(**r)
        return None

    def upsert_product(self, data: ProductPim) -> ProductPim:
        now = datetime.utcnow()
        self._ch.command(
            "INSERT INTO dim_product_pim (organization_id, marketplace, account_id, product_id, title,"
            " description, seo_keywords, brand_id, category_id, images, updated_at)"
            " VALUES ({oid:String}, {mp:String}, {aid:String}, {pid:String}, {title:String},"
            " {desc:String}, {seo:String}, {bid:Nullable(String)}, {cid:Nullable(String)},"
            " {images:Array(String)}, {updated:DateTime})",
            parameters={
                "oid": data.organization_id,
                "mp": data.marketplace,
                "aid": data.account_id,
                "pid": data.product_id,
                "title": data.title,
                "desc": data.description,
                "seo": data.seo_keywords,
                "bid": data.brand_id,
                "cid": data.category_id,
                "images": data.images,
                "updated": now,
            },
        )
        return ProductPim(
            organization_id=data.organization_id,
            marketplace=data.marketplace,
            account_id=data.account_id,
            product_id=data.product_id,
            title=data.title,
            description=data.description,
            seo_keywords=data.seo_keywords,
            brand_id=data.brand_id,
            category_id=data.category_id,
            images=data.images,
            updated_at=now,
        )

    def update_product(self, marketplace: str, account_id: str, product_id: str, data: ProductPimUpdate) -> ProductPim | None:
        existing = self.get_product(marketplace, account_id, product_id)
        if not existing:
            return None
        merged = ProductPim(
            organization_id=existing.organization_id,
            marketplace=marketplace,
            account_id=account_id,
            product_id=product_id,
            title=data.title if data.title is not None else existing.title,
            description=data.description if data.description is not None else existing.description,
            seo_keywords=data.seo_keywords if data.seo_keywords is not None else existing.seo_keywords,
            brand_id=data.brand_id if data.brand_id is not None else existing.brand_id,
            category_id=data.category_id if data.category_id is not None else existing.category_id,
            images=data.images if data.images is not None else existing.images,
            updated_at=datetime.utcnow(),
        )
        return self.upsert_product(merged)

    def bulk_update_products(self, organization_id: str, updates: list[ProductPimBulkUpdateItem]) -> int:
        count = 0
        for upd in updates:
            self.update_product(upd.marketplace, upd.account_id, upd.product_id, upd)
            count += 1
        return count
