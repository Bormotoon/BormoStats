from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AdCampaign(BaseModel):
    campaign_id: str
    marketplace: str
    account_id: str
    title: str
    status: str
    daily_budget: float | None = None
    current_cpm: float | None = None
    current_cpc: float | None = None
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
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdRuleCreate(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=2, max_length=10, pattern=r"^(wb|ozon)$")
    account_id: str = Field(default="default", max_length=64)
    target_cpm: float = Field(default=0, ge=0)
    max_cpm: float = Field(default=0, ge=0)
    target_position: int = Field(default=0, ge=0, le=100)


class AdRuleUpdate(BaseModel):
    target_cpm: float | None = Field(default=None, ge=0)
    max_cpm: float | None = Field(default=None, ge=0)
    target_position: int | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None
