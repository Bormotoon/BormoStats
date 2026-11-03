from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

MARKETPLACE_PATTERN = r"^(wb|ozon|ym)$"
ACCOUNT_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,64}$"
PLACEMENT_PATTERN = r"^(combined|search|recommendations)$"


class AdCampaign(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(pattern=MARKETPLACE_PATTERN)
    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    title: str = Field(default="", max_length=500)
    status: str = Field(default="", max_length=64)
    daily_budget: float | None = Field(default=None, ge=0)
    current_cpm: float | None = Field(default=None, ge=0)
    current_cpc: float | None = Field(default=None, ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdRule(BaseModel):
    rule_id: str
    campaign_id: str
    marketplace: str
    account_id: str
    target_cpm: float = 0
    max_cpm: float = 0
    target_position: int = 0
    product_id: str = ""
    placement: str = "combined"
    is_active: bool = True
    dry_run: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdRuleCreate(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=2, max_length=10, pattern=MARKETPLACE_PATTERN)
    account_id: str = Field(default="default", pattern=ACCOUNT_ID_PATTERN)
    target_cpm: float = Field(default=0, ge=0)
    max_cpm: float = Field(default=0, ge=0)
    target_position: int = Field(default=0, ge=0, le=100)
    product_id: str = Field(
        default="", max_length=128, description="SKU/article managed by the rule"
    )
    placement: str = Field(default="combined", pattern=PLACEMENT_PATTERN)
    dry_run: bool = Field(
        default=True,
        description="New rules only simulate bid changes until explicitly switched off",
    )

    @model_validator(mode="after")
    def _validate_marketplace_fields(self) -> AdRuleCreate:
        validate_rule_for_marketplace(self)
        return self

    @model_validator(mode="before")
    @classmethod
    def _defaults_for_ym_ui(cls, values: object) -> object:
        if isinstance(values, dict) and values.get("marketplace") == "ym":
            return {"target_cpm": 0.5, **values}
        return values


class AdRuleUpdate(BaseModel):
    target_cpm: float | None = Field(default=None, ge=0)
    max_cpm: float | None = Field(default=None, ge=0)
    target_position: int | None = Field(default=None, ge=0, le=100)
    placement: str | None = Field(default=None, pattern=PLACEMENT_PATTERN)
    is_active: bool | None = None
    dry_run: bool | None = None


def validate_rule_for_marketplace(rule: AdRule | AdRuleCreate) -> None:
    marketplace = rule.marketplace.lower()
    value = rule.product_id or ""
    if marketplace == "ym":
        if not value:
            raise ValueError("YM product_id is required")
        if not 0.5 <= rule.target_cpm <= 99.99:
            raise ValueError("YM bids must be between 0.5 and 99.99 percent")
        if rule.max_cpm != 0 and not 0.5 <= rule.max_cpm <= 99.99:
            raise ValueError("YM max bid must be 0 (unbounded) or between 0.5 and 99.99")
        if rule.max_cpm and rule.max_cpm < rule.target_cpm:
            raise ValueError("YM max bid must not be below target bid")
        if rule.target_position != 0 or rule.placement != "combined":
            raise ValueError("YM supports only combined placement without target_position")
    elif value and not value.isdigit():
        raise ValueError("product_id must be numeric for this marketplace")
    elif value and len(value) > 128:
        raise ValueError("product_id too long")
