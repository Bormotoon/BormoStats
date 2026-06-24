from __future__ import annotations

from datetime import datetime
from typing import Any

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_key_or_org_role
from app.models.organization import OrgMemberRole
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/extension", tags=["extension"], responses=API_ERROR_RESPONSES)


@router.post("/positions", status_code=status.HTTP_201_CREATED)
def receive_positions(
    body: list[dict[str, Any]],
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> dict[str, int]:
    now = datetime.utcnow()
    count = 0
    for item in body:
        ch.command(
            "INSERT INTO raw_serp_positions (account_id, marketplace, keyword, product_id, position, search_ts)"
            " VALUES ({aid:String}, {mp:String}, {kw:String}, {pid:UInt64}, {pos:UInt16}, {ts:DateTime})",
            parameters={
                "aid": item.get("account_id", "default"),
                "mp": item.get("marketplace", "wb"),
                "kw": item.get("keyword", ""),
                "pid": int(item["product_id"]),
                "pos": int(item["position"]),
                "ts": datetime.fromisoformat(item.get("search_ts", now.isoformat())),
            },
        )
        count += 1
    return {"inserted": count}


@router.post("/competitor-price", status_code=status.HTTP_201_CREATED)
def receive_competitor_price(
    body: list[dict[str, Any]],
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> dict[str, int]:
    now = datetime.utcnow()
    count = 0
    for item in body:
        ch.command(
            "INSERT INTO raw_competitor_price_tracker"
            " (account_id, marketplace, competitor_product_id, competitor_name, price_rub,"
            " price_with_discount_rub, in_stock, tracked_product_id, snapshot_ts)"
            " VALUES ({aid:String}, {mp:String}, {cpid:String}, {cname:String}, {price:Float64},"
            " {pwd:Nullable(Float64)}, {stock:UInt8}, {tpid:Nullable(String)}, {ts:DateTime})",
            parameters={
                "aid": item.get("account_id", "default"),
                "mp": item.get("marketplace", "wb"),
                "cpid": item["competitor_product_id"],
                "cname": item.get("competitor_name", ""),
                "price": float(item["price_rub"]),
                "pwd": item.get("price_with_discount_rub"),
                "stock": 1 if item.get("in_stock", True) else 0,
                "tpid": item.get("tracked_product_id"),
                "ts": datetime.fromisoformat(item.get("snapshot_ts", now.isoformat())),
            },
        )
        count += 1
    return {"inserted": count}
