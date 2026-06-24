from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PriceRule(BaseModel):
    rule_id: str
    marketplace: str
    account_id: str
    product_id: str
    min_price: float = 0
    max_price: float = 0
    target_margin_percent: float = 0
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PriceRuleCreate(BaseModel):
    marketplace: str = Field(min_length=2, max_length=10, pattern=r"^(wb|ozon)$")
    account_id: str = Field(default="default", max_length=64)
    product_id: str = Field(min_length=1, max_length=64)
    min_price: float = Field(default=0, ge=0)
    max_price: float = Field(default=0, ge=0)
    target_margin_percent: float = Field(default=0, ge=0, le=100)


class PriceRuleUpdate(BaseModel):
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    target_margin_percent: float | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None


class BreakevenRow(BaseModel):
    day: str
    marketplace: str
    account_id: str
    product_id: str
    current_price: float
    cost_price: float
    commission_pct: float
    logistics_rub: float
    breakeven_price: float
    min_recommended_price: float
