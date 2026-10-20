from __future__ import annotations

from app.models.bidder import ACCOUNT_ID_PATTERN
from app.models.repricer import NoDiscountFallback, PriceMode
from pydantic import BaseModel, Field

OFFER_ID_MAX = 128


class PriceBreakdownRow(BaseModel):
    """One card of ``mrt_price_current`` with the price rule set for it, if any.

    Percentages are 0..100. ``mp_discount_scope`` says where the marketplace's discount
    comes from: ``product`` (the card's recent sales), ``account`` (the account's median, an
    estimate) or empty (no sales to measure it on).
    """

    marketplace: str
    account_id: str
    offer_id: str
    product_id: str
    title: str | None = None
    image_url: str | None = None
    list_price: float
    seller_discount_pct: float
    seller_price: float
    mp_discount_pct: float | None = None
    mp_discount_scope: str = ""
    mp_discount_samples: int = 0
    buyer_price: float | None = None
    commission_pct: float
    commission_rub: float
    acquiring_rub: float
    logistics_rub: float
    fees_rub: float
    cost_price: float | None = None
    margin_rub: float | None = None
    margin_pct: float | None = None
    breakeven_price: float | None = None
    min_price: float | None = None
    auto_actions_enabled: bool | None = None
    price_seen_at: str | None = None
    rule_id: str | None = None
    mode: str | None = None
    target_price: float | None = None
    no_discount_fallback: str | None = None
    rule_is_active: bool | None = None
    rule_dry_run: bool | None = None
    target_gap_pct: float | None = Field(
        default=None,
        description="How far the kept price (buyer or seller, by mode) is from the target, %",
    )


class PriceCompareRow(BaseModel):
    offer_id: str
    title: str | None = None
    image_url: str | None = None
    wb_seller_price: float | None = None
    wb_buyer_price: float | None = None
    ozon_seller_price: float | None = None
    ozon_buyer_price: float | None = None
    buyer_spread_pct: float | None = Field(
        default=None, description="(max - min) / min of the buyer prices, %"
    )


class TargetPriceSet(BaseModel):
    """Desired price of one card; creates or updates the card's price rule."""

    account_id: str = Field(default="default", pattern=ACCOUNT_ID_PATTERN)
    target_price: float = Field(gt=0, le=10_000_000)
    mode: PriceMode = "buyer_price"
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    max_step_pct: float | None = Field(default=None, gt=0, le=50)
    no_discount_fallback: NoDiscountFallback | None = Field(
        default=None,
        description="Kept as is when omitted; a new rule keeps the target as the seller price"
        " on Ozon until 3 sales measure the discount and waits for them on WB",
    )


class OfferCost(BaseModel):
    offer_id: str
    cost_price_rub: float
    updated_at: str | None = None


class OfferCostSet(BaseModel):
    cost_price_rub: float = Field(gt=0, le=10_000_000)


class OfferCostImport(BaseModel):
    """Rows ``article;cost`` (``,`` / tab separators and a decimal comma are accepted)."""

    text: str = Field(min_length=1, max_length=2_000_000)


class OfferCostImportResult(BaseModel):
    imported: int
    errors: list[str]
    updated: list[str] = Field(
        default_factory=list, description="Articles whose cost was set, sorted"
    )


class TargetPriceImport(BaseModel):
    """Rows ``article;desired price`` of one marketplace, from a spreadsheet."""

    marketplace: str = Field(pattern=r"^(wb|ozon)$")
    text: str = Field(min_length=1, max_length=2_000_000)


class TargetPriceImportResult(BaseModel):
    imported: int
    errors: list[str]
    not_found: list[str] = Field(
        default_factory=list, description="Articles with no card on the marketplace"
    )
    updated: list[str] = Field(
        default_factory=list, description="Articles whose desired price was set, sorted"
    )


class KeepPrices(BaseModel):
    """Keep the desired prices of a marketplace live (``keep``) or only simulate them."""

    marketplace: str = Field(pattern=r"^(wb|ozon)$")
    keep: bool


class KeepPricesResult(BaseModel):
    rules: int
    marketplace_actions_enabled: bool
