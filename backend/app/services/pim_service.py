"""PIM: brands, categories and product enrichment, scoped to one organization."""

from __future__ import annotations

import uuid

from app.db.ch import insert_values_sql, utc_now
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
from app.services.tenancy import ensure_account_access
from clickhouse_connect.driver import Client

_BRAND_COLUMNS: tuple[tuple[str, str], ...] = (
    ("brand_id", "String"),
    ("organization_id", "String"),
    ("name", "String"),
    ("description", "String"),
    ("logo_url", "String"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_CATEGORY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("category_id", "String"),
    ("organization_id", "String"),
    ("name", "String"),
    ("parent_id", "Nullable(String)"),
    ("path", "String"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_PRODUCT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("organization_id", "String"),
    ("marketplace", "String"),
    ("account_id", "String"),
    ("product_id", "String"),
    ("title", "String"),
    ("description", "String"),
    ("seo_keywords", "String"),
    ("brand_id", "Nullable(String)"),
    ("category_id", "Nullable(String)"),
    ("images", "Array(String)"),
    ("updated_at", "DateTime"),
)
_BRAND_COLS = ", ".join(name for name, _ in _BRAND_COLUMNS)
_CATEGORY_COLS = ", ".join(name for name, _ in _CATEGORY_COLUMNS)
_PRODUCT_COLS = ", ".join(name for name, _ in _PRODUCT_COLUMNS)
_BRAND_INSERT = insert_values_sql("dim_brand", _BRAND_COLUMNS)
_CATEGORY_INSERT = insert_values_sql("dim_category", _CATEGORY_COLUMNS)
_PRODUCT_INSERT = insert_values_sql("dim_product_pim", _PRODUCT_COLUMNS)
_PRODUCT_LIST_LIMIT = 500


class PimService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    # -- Brands -------------------------------------------------------------------

    def list_brands(self) -> list[Brand]:
        rows = self._ch.query(
            f"SELECT {_BRAND_COLS} FROM dim_brand FINAL"
            " WHERE organization_id = {oid:String} ORDER BY name",
            parameters={"oid": self._org},
        )
        return [Brand(**r) for r in rows.named_results()]

    def get_brand(self, brand_id: str) -> Brand | None:
        rows = self._ch.query(
            f"SELECT {_BRAND_COLS} FROM dim_brand FINAL"
            " WHERE organization_id = {oid:String} AND brand_id = {bid:String} LIMIT 1",
            parameters={"oid": self._org, "bid": brand_id},
        )
        for r in rows.named_results():
            return Brand(**r)
        return None

    def create_brand(self, data: BrandCreate) -> Brand:
        now = utc_now()
        brand = Brand(
            brand_id=data.brand_id or str(uuid.uuid4()),
            organization_id=self._org,
            name=data.name,
            description=data.description,
            logo_url=data.logo_url,
            created_at=now,
            updated_at=now,
        )
        self._ch.command(_BRAND_INSERT, parameters=brand.model_dump())
        return brand

    def update_brand(self, brand_id: str, data: BrandUpdate) -> Brand | None:
        existing = self.get_brand(brand_id)
        if existing is None:
            return None
        now = utc_now()
        brand = existing.model_copy(
            update={
                **data.model_dump(exclude_none=True),
                "created_at": existing.created_at or now,
                "updated_at": now,
            }
        )
        self._ch.command(_BRAND_INSERT, parameters=brand.model_dump())
        return brand

    def delete_brand(self, brand_id: str) -> bool:
        if self.get_brand(brand_id) is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_brand DELETE"
            " WHERE organization_id = {oid:String} AND brand_id = {bid:String}",
            parameters={"oid": self._org, "bid": brand_id},
        )
        return True

    # -- Categories ---------------------------------------------------------------

    def list_categories(self) -> list[Category]:
        rows = self._ch.query(
            f"SELECT {_CATEGORY_COLS} FROM dim_category FINAL"
            " WHERE organization_id = {oid:String} ORDER BY name",
            parameters={"oid": self._org},
        )
        return [Category(**r) for r in rows.named_results()]

    def get_category(self, category_id: str) -> Category | None:
        rows = self._ch.query(
            f"SELECT {_CATEGORY_COLS} FROM dim_category FINAL"
            " WHERE organization_id = {oid:String} AND category_id = {cid:String} LIMIT 1",
            parameters={"oid": self._org, "cid": category_id},
        )
        for r in rows.named_results():
            return Category(**r)
        return None

    def _category_path(self, name: str, parent_id: str | None) -> str:
        if parent_id:
            parent = self.get_category(parent_id)
            if parent is not None:
                return f"{parent.path}/{name}"
        return name

    def create_category(self, data: CategoryCreate) -> Category:
        now = utc_now()
        category = Category(
            category_id=data.category_id or str(uuid.uuid4()),
            organization_id=self._org,
            name=data.name,
            parent_id=data.parent_id,
            path=self._category_path(data.name, data.parent_id),
            created_at=now,
            updated_at=now,
        )
        self._ch.command(_CATEGORY_INSERT, parameters=category.model_dump())
        return category

    def update_category(self, category_id: str, data: CategoryUpdate) -> Category | None:
        existing = self.get_category(category_id)
        if existing is None:
            return None
        now = utc_now()
        name = data.name or existing.name
        parent_id = data.parent_id if data.parent_id is not None else existing.parent_id
        category = existing.model_copy(
            update={
                "name": name,
                "parent_id": parent_id,
                "path": self._category_path(name, parent_id),
                "created_at": existing.created_at or now,
                "updated_at": now,
            }
        )
        self._ch.command(_CATEGORY_INSERT, parameters=category.model_dump())
        return category

    def delete_category(self, category_id: str) -> bool:
        if self.get_category(category_id) is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_category DELETE"
            " WHERE organization_id = {oid:String} AND category_id = {cid:String}",
            parameters={"oid": self._org, "cid": category_id},
        )
        return True

    # -- Product PIM --------------------------------------------------------------

    def list_products(
        self,
        marketplace: str | None = None,
        account_id: str | None = None,
        q: str | None = None,
    ) -> list[ProductPim]:
        where = ["organization_id = {oid:String}"]
        params: dict[str, object] = {"oid": self._org, "lim": _PRODUCT_LIST_LIMIT}
        if marketplace:
            where.append("marketplace = {mp:String}")
            params["mp"] = marketplace
        if account_id:
            where.append("account_id = {aid:String}")
            params["aid"] = account_id
        if q:
            where.append(
                "(positionCaseInsensitiveUTF8(title, {q:String}) > 0 OR product_id = {q:String})"
            )
            params["q"] = q
        rows = self._ch.query(
            f"SELECT {_PRODUCT_COLS} FROM dim_product_pim FINAL"
            f" WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT {{lim:UInt32}}",
            parameters=params,
        )
        return [ProductPim(**r) for r in rows.named_results()]

    def get_product(self, marketplace: str, account_id: str, product_id: str) -> ProductPim | None:
        rows = self._ch.query(
            f"SELECT {_PRODUCT_COLS} FROM dim_product_pim FINAL"
            " WHERE organization_id = {oid:String} AND marketplace = {mp:String}"
            " AND account_id = {aid:String} AND product_id = {pid:String} LIMIT 1",
            parameters={"oid": self._org, "mp": marketplace, "aid": account_id, "pid": product_id},
        )
        for r in rows.named_results():
            return ProductPim(**r)
        return None

    def upsert_product(self, data: ProductPim) -> ProductPim:
        product = data.model_copy(update={"organization_id": self._org, "updated_at": utc_now()})
        self._ch.command(_PRODUCT_INSERT, parameters=product.model_dump())
        return product

    def update_product(
        self, marketplace: str, account_id: str, product_id: str, data: ProductPimUpdate
    ) -> ProductPim | None:
        existing = self.get_product(marketplace, account_id, product_id)
        if existing is None:
            # Enrichment of a product the org owns but has not edited yet.
            ensure_account_access(self._ch, self._org, marketplace, account_id)
            existing = ProductPim(
                organization_id=self._org,
                marketplace=marketplace,
                account_id=account_id,
                product_id=product_id,
            )
        changes = ProductPimUpdate.model_validate(data.model_dump()).model_dump(exclude_none=True)
        return self.upsert_product(existing.model_copy(update=changes))

    def bulk_update_products(self, updates: list[ProductPimBulkUpdateItem]) -> int:
        for account in {(u.marketplace, u.account_id) for u in updates}:
            ensure_account_access(self._ch, self._org, *account)
        for upd in updates:
            self.update_product(upd.marketplace, upd.account_id, upd.product_id, upd)
        return len(updates)
