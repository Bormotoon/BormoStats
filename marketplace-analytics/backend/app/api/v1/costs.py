"""Product cost management endpoints (unit economics)."""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_api_key
from app.models.admin import ProductCostCreate, ProductCostUpdate
from fastapi import APIRouter, Depends

router = APIRouter(
    prefix="/costs",
    tags=["costs"],
    responses=API_ERROR_RESPONSES,
)


@router.get("/")
def list_costs(
    client: ChClientDependency,
    marketplace: str | None = None,
) -> dict[str, object]:
    """List all product cost prices."""
    where = ""
    params: dict[str, object] = {}
    if marketplace:
        where = " WHERE marketplace = %(marketplace)s"
        params["marketplace"] = marketplace
    rows = client.query(
        "SELECT marketplace, product_id, cost_price_rub, updated_at"
        " FROM dim_product_cost FINAL" + where,
        parameters=params,
    )
    items = [
        {
            "marketplace": r[0],
            "product_id": r[1],
            "cost_price_rub": float(r[2]),
            "updated_at": str(r[3]),
        }
        for r in rows.result_rows
    ]
    return {"items": items}


@router.put("/{marketplace}/{product_id}")
def upsert_cost(
    client: ChClientDependency,
    marketplace: str,
    product_id: int,
    body: ProductCostCreate | ProductCostUpdate,
    _admin: None = Depends(require_admin_api_key),
) -> dict[str, object]:
    """Set product cost price."""
    cost_price = body.cost_price_rub
    client.command(
        "INSERT INTO dim_product_cost (marketplace, product_id, cost_price_rub) VALUES",
        [[marketplace, product_id, cost_price]],
    )
    return {
        "status": "ok",
        "marketplace": marketplace,
        "product_id": product_id,
        "cost_price_rub": cost_price,
    }


@router.delete("/{marketplace}/{product_id}")
def delete_cost(
    client: ChClientDependency,
    marketplace: str,
    product_id: int,
    _admin: None = Depends(require_admin_api_key),
) -> dict[str, object]:
    """Remove product cost entry."""
    client.command(
        "ALTER TABLE dim_product_cost DELETE WHERE marketplace = %(marketplace)s"
        " AND product_id = %(product_id)s",
        parameters={"marketplace": marketplace, "product_id": product_id},
    )
    return {"status": "deleted", "marketplace": marketplace, "product_id": product_id}
