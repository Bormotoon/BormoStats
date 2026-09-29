"""Product cost management endpoints (unit economics).

``dim_product_cost`` is keyed by ``(marketplace, product_id)`` without an
organization column, so cost data is platform-level and managed with the master
admin key only.
"""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import require_platform_admin
from app.core.deps import ChClientDependency
from app.db.ch import utc_now
from app.models.admin import ProductCostUpdate
from fastapi import APIRouter, Depends, Path, Query

router = APIRouter(
    prefix="/costs",
    tags=["costs"],
    responses=API_ERROR_RESPONSES,
    dependencies=[Depends(require_platform_admin)],
)

MarketplacePath = Path(pattern=r"^(wb|ozon)$")


@router.get("/")
def list_costs(
    client: ChClientDependency,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    limit: int = Query(default=5000, ge=1, le=50_000),
) -> dict[str, object]:
    """List product cost prices."""
    where = " WHERE marketplace = {mp:String}" if marketplace else ""
    rows = client.query(
        "SELECT marketplace, product_id, cost_price_rub, updated_at"
        f" FROM dim_product_cost FINAL{where} ORDER BY marketplace, product_id"
        " LIMIT {lim:UInt32}",
        parameters={"mp": marketplace or "", "lim": limit},
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
    body: ProductCostUpdate,
    marketplace: str = MarketplacePath,
    product_id: int = Path(ge=1),
) -> dict[str, object]:
    """Set product cost price."""
    client.insert(
        "dim_product_cost",
        [[marketplace, product_id, body.cost_price_rub, utc_now()]],
        column_names=["marketplace", "product_id", "cost_price_rub", "updated_at"],
    )
    return {
        "status": "ok",
        "marketplace": marketplace,
        "product_id": product_id,
        "cost_price_rub": body.cost_price_rub,
    }


@router.delete("/{marketplace}/{product_id}")
def delete_cost(
    client: ChClientDependency,
    marketplace: str = MarketplacePath,
    product_id: int = Path(ge=1),
) -> dict[str, object]:
    """Remove product cost entry."""
    client.command(
        "ALTER TABLE dim_product_cost DELETE"
        " WHERE marketplace = {mp:String} AND product_id = {pid:UInt64}",
        parameters={"mp": marketplace, "pid": product_id},
    )
    return {"status": "deleted", "marketplace": marketplace, "product_id": product_id}
