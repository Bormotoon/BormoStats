"""Typed admin request and response models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

BACKFILL_MAX_DAYS: dict[tuple[str, str], int] = {
    ("wb", "sales"): 90,
    ("wb", "orders"): 90,
    ("wb", "funnel"): 90,
    ("ozon", "postings"): 90,
    ("ozon", "finance"): 365,
    ("marts", "build"): 365,
}


class BackfillMarketplace(StrEnum):
    WB = "wb"
    OZON = "ozon"
    MARTS = "marts"


class BackfillDataset(StrEnum):
    SALES = "sales"
    ORDERS = "orders"
    FUNNEL = "funnel"
    POSTINGS = "postings"
    FINANCE = "finance"
    BUILD = "build"


@dataclass(frozen=True)
class AdminRequestContext:
    path: str
    method: str
    remote_addr: str
    forwarded_for: str | None
    user_agent: str | None


class ActionQueueResponse(BaseModel):
    action: str
    task_name: str
    task_id: str
    queued_at: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class BackfillRequest(BaseModel):
    marketplace: BackfillMarketplace
    dataset: BackfillDataset
    days: int = Field(default=14, ge=1, le=365)

    @model_validator(mode="after")
    def validate_target(self) -> BackfillRequest:
        target = (self.marketplace.value, self.dataset.value)
        max_days = BACKFILL_MAX_DAYS.get(target)
        if max_days is None:
            raise ValueError(
                f"unsupported backfill target: {self.marketplace.value}:{self.dataset.value}"
            )
        if self.days > max_days:
            raise ValueError(
                f"days exceeds limit for {self.marketplace.value}:{self.dataset.value} "
                f"(max {max_days})"
            )
        return self


class TransformRecentRequest(BaseModel):
    pass


class TransformBackfillRequest(BaseModel):
    days: int = Field(default=14, ge=1, le=365)


class BuildMartsRecentRequest(BaseModel):
    pass


class BuildMartsBackfillRequest(BaseModel):
    days: int = Field(default=14, ge=1, le=365)


class RunAutomationRulesRequest(BaseModel):
    pass


class PruneOldRawRequest(BaseModel):
    days: int = Field(default=120, ge=30, le=3650)
