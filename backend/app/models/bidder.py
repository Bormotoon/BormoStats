from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

MARKETPLACE_PATTERN = r"^(wb|ozon)$"
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
        default="",
        max_length=64,
        pattern=r"^[0-9]*$",
        description="WB article (nm_id) whose bid the rule manages",
    )
    placement: str = Field(default="combined", pattern=PLACEMENT_PATTERN)
    dry_run: bool = Field(
        default=True,
        description="New rules only simulate bid changes until explicitly switched off",
    )


class AdRuleUpdate(BaseModel):
    target_cpm: float | None = Field(default=None, ge=0)
    max_cpm: float | None = Field(default=None, ge=0)
    target_position: int | None = Field(default=None, ge=0, le=100)
    placement: str | None = Field(default=None, pattern=PLACEMENT_PATTERN)
    is_active: bool | None = None
    dry_run: bool | None = None
