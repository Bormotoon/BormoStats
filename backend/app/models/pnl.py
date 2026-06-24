from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AdditionalExpense(BaseModel):
    expense_id: str
    organization_id: str = "default"
    category: str
    amount_rub: float
    month: str
    description: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdditionalExpenseCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    amount_rub: float = Field(ge=0)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    description: str = Field(default="", max_length=500)
    organization_id: str = Field(default="default", max_length=64)


class AdditionalExpenseUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=100)
    amount_rub: float | None = Field(default=None, ge=0)
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    description: str | None = Field(default=None, max_length=500)


class PnlRow(BaseModel):
    month: str
    organization_id: str
    marketplace: str
    account_id: str
    revenue_rub: float
    commission_rub: float
    logistics_rub: float
    returns_cost_rub: float
    gross_profit_rub: float
    ad_cost_rub: float
    additional_expenses_rub: float
    operating_profit_rub: float
    ebitda_rub: float
    net_profit_rub: float
    margin_pct: float
