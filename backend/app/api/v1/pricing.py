"""Prices: breakdown per card, comparison across marketplaces, desired prices, cost prices."""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AdminAuth, AuthContext, ManagerAuth
from app.core.deps import ChClientDependency
from app.models.pricing import (
    OFFER_ID_MAX,
    OfferCost,
    OfferCostImport,
    OfferCostImportResult,
    OfferCostSet,
    PriceBreakdownRow,
    PriceCompareRow,
    TargetPriceSet,
)
from app.models.repricer import PriceRule
from app.services.pricing_service import PricingService
from fastapi import APIRouter, HTTPException, Path, Query, status

router = APIRouter(prefix="/pricing", tags=["pricing"], responses=API_ERROR_RESPONSES)

MarketplacePath = Path(pattern=r"^(wb|ozon)$")
OfferPath = Path(min_length=1, max_length=OFFER_ID_MAX)


def _svc(ch: ChClientDependency, auth: AuthContext) -> PricingService:
    return PricingService(ch, auth.organization_id)


@router.get("/breakdown")
def price_breakdown(
    ch: ChClientDependency,
    auth: ManagerAuth,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    account_id: str | None = Query(default=None, max_length=64),
) -> list[PriceBreakdownRow]:
    """Per card: list price, seller and marketplace discounts, buyer price, fees, margin."""
    return _svc(ch, auth).breakdown(marketplace, account_id)


@router.get("/compare")
def price_compare(
    ch: ChClientDependency,
    auth: ManagerAuth,
    account_id: str | None = Query(default=None, max_length=64),
) -> list[PriceCompareRow]:
    """Seller and buyer prices of each supplier article on every marketplace."""
    return _svc(ch, auth).compare(account_id)


@router.put("/target/{marketplace}/{offer_id}")
def set_target_price(
    body: TargetPriceSet,
    ch: ChClientDependency,
    auth: AdminAuth,
    marketplace: str = MarketplacePath,
    offer_id: str = OfferPath,
) -> PriceRule:
    """Set the desired price of a card. A new rule starts in dry-run."""
    return _svc(ch, auth).set_target(marketplace, offer_id, body)


@router.get("/costs")
def list_costs(ch: ChClientDependency, auth: ManagerAuth) -> list[OfferCost]:
    return _svc(ch, auth).list_costs()


@router.put("/costs/{offer_id}")
def set_cost(
    body: OfferCostSet,
    ch: ChClientDependency,
    auth: AdminAuth,
    offer_id: str = OfferPath,
) -> dict[str, object]:
    _svc(ch, auth).set_costs({offer_id: body.cost_price_rub})
    return {"offer_id": offer_id, "cost_price_rub": body.cost_price_rub}


@router.delete("/costs/{offer_id}")
def delete_cost(
    ch: ChClientDependency,
    auth: AdminAuth,
    offer_id: str = OfferPath,
) -> dict[str, bool]:
    if not _svc(ch, auth).delete_cost(offer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cost not found")
    return {"deleted": True}


@router.post("/costs/import")
def import_costs(
    body: OfferCostImport,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> OfferCostImportResult:
    """Import ``article;cost`` lines pasted from a spreadsheet."""
    return _svc(ch, auth).import_costs(body.text)
