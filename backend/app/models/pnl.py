from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class AdditionalExpense(BaseModel):
    expense_id: str
    organization_id: str = "default"
    category: str
    amount_rub: float
    month: str
    expense_date: date | None = Field(default=None, ge=date(1970, 1, 1), le=date(2149, 6, 6))
    description: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdditionalExpenseCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    amount_rub: float = Field(ge=0)
    month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    expense_date: date | None = Field(default=None, ge=date(1970, 1, 1), le=date(2149, 6, 6))
    description: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def resolve_month(self):
        if self.expense_date is not None:
            month = self.expense_date.strftime("%Y-%m")
            if self.month is not None and self.month != month:
                raise ValueError("month must match expense_date")
            self.month = month
        if self.month is None:
            raise ValueError("expense_date or month is required")
        return self


class AdditionalExpenseUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=100)
    amount_rub: float | None = Field(default=None, ge=0)
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    expense_date: date | None = Field(default=None, ge=date(1970, 1, 1), le=date(2149, 6, 6))
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_month(self):
        if self.expense_date is not None and self.month is not None and self.month != self.expense_date.strftime("%Y-%m"):
            raise ValueError("month must match expense_date")
        return self


class PnlRow(BaseModel):
    month: str
    organization_id: str
    marketplace: str
    account_id: str
    revenue_rub: float
    commission_rub: float
    logistics_rub: float
    returns_cost_rub: float
    storage_rub: float = 0.0
    other_costs_rub: float = 0.0
    # what the marketplace accrued to the balance: revenue minus every marketplace charge
    net_accrued_rub: float = 0.0
    financing_adjustment_rub: float = 0.0
    cogs_rub: float = 0.0
    gross_profit_rub: float
    ad_cost_rub: float
    additional_expenses_rub: float
    operating_profit_rub: float
    ebitda_rub: float
    net_profit_rub: float | None
    tax_enabled: bool = False
    tax_rate_pct: float = 0.0
    tax_base_rub: float | None = None
    tax_rub: float | None = None
    tax_status: str = "disabled"
    profit_before_tax_rub: float | None = None
    realization_fetched_at: str | None = None
    margin_pct: float
