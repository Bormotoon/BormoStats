from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.models.bidder import ACCOUNT_ID_PATTERN, MARKETPLACE_PATTERN
from pydantic import BaseModel, Field

# what a price rule keeps (see workers/app/tasks/repricer.py)
PriceMode = Literal["buyer_price", "seller_price", "margin"]
# what a buyer_price rule does while the card's marketplace discount cannot be measured:
# wait (""), use the account's median discount, or keep the target as the seller price
NoDiscountFallback = Literal["", "account_median", "seller_price"]
# where the account's median discount says something about a card without sales: WB's SPP is
# much the same across a seller's cards, Ozon's "баллы за скидки" are given per card
ACCOUNT_MEDIAN_MARKETPLACES = frozenset({"wb"})


class FallbackNotAllowedError(ValueError):
    """A no_discount_fallback the rule's marketplace does not support."""


def check_fallback(marketplace: str, fallback: str | None) -> None:
    if fallback == "account_median" and marketplace not in ACCOUNT_MEDIAN_MARKETPLACES:
        raise FallbackNotAllowedError(
            f"no_discount_fallback 'account_median' is not available on {marketplace}:"
            " its discounts vary between cards"
        )


class PriceRule(BaseModel):
    rule_id: str
    marketplace: str
    account_id: str
    product_id: str = Field(description="Supplier article: WB vendorCode or Ozon offer_id")
    mode: str = "margin"
    target_price: float = 0
    max_step_pct: float = 10
    no_discount_fallback: str = ""
    min_price: float = 0
    max_price: float = 0
    target_margin_percent: float = 0
    is_active: bool = True
    dry_run: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PriceRuleCreate(BaseModel):
    marketplace: str = Field(min_length=2, max_length=10, pattern=MARKETPLACE_PATTERN)
    account_id: str = Field(default="default", pattern=ACCOUNT_ID_PATTERN)
    product_id: str = Field(
        min_length=1, max_length=128, description="Supplier article: WB vendorCode or Ozon offer_id"
    )
    mode: PriceMode = "margin"
    target_price: float = Field(default=0, ge=0, le=10_000_000)
    max_step_pct: float = Field(default=10, gt=0, le=50)
    no_discount_fallback: NoDiscountFallback = ""
    min_price: float = Field(default=0, ge=0)
    max_price: float = Field(default=0, ge=0)
    target_margin_percent: float = Field(default=0, ge=0, le=100)
    dry_run: bool = Field(
        default=True,
        description="New rules only simulate price changes until explicitly switched off",
    )


class PriceRuleUpdate(BaseModel):
    mode: PriceMode | None = None
    target_price: float | None = Field(default=None, ge=0, le=10_000_000)
    max_step_pct: float | None = Field(default=None, gt=0, le=50)
    no_discount_fallback: NoDiscountFallback | None = None
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    target_margin_percent: float | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None
    dry_run: bool | None = None


class BreakevenRow(BaseModel):
    marketplace: str
    account_id: str
    offer_id: str
    product_id: str
    current_price: float
    cost_price: float | None
    commission_pct: float
    logistics_rub: float
    breakeven_price: float | None
