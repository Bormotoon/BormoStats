"""Payloads accepted from the browser extension."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.models.bidder import ACCOUNT_ID_PATTERN
from pydantic import BaseModel, Field, field_validator

MAX_EXTENSION_BATCH = 500
_MAX_FUTURE_SKEW = timedelta(hours=1)
_MAX_AGE = timedelta(days=365)


def _normalize_ts(value: datetime | None) -> datetime:
    now = datetime.now(UTC)
    if value is None:
        return now.replace(microsecond=0)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if value > now + _MAX_FUTURE_SKEW:
        raise ValueError("timestamp is in the future")
    if value < now - _MAX_AGE:
        raise ValueError("timestamp is older than 365 days")
    return value.astimezone(UTC).replace(microsecond=0)


class SerpPosition(BaseModel):
    account_id: str = Field(default="default", pattern=ACCOUNT_ID_PATTERN)
    marketplace: str = Field(default="wb", pattern=r"^(wb|ozon)$")
    keyword: str = Field(min_length=1, max_length=256)
    product_id: int = Field(ge=1, le=2**63 - 1)
    position: int = Field(ge=1, le=10_000)
    search_ts: datetime | None = None

    @field_validator("search_ts")
    @classmethod
    def _check_ts(cls, value: datetime | None) -> datetime:
        return _normalize_ts(value)


class CompetitorPrice(BaseModel):
    account_id: str = Field(default="default", pattern=ACCOUNT_ID_PATTERN)
    marketplace: str = Field(default="wb", pattern=r"^(wb|ozon)$")
    competitor_product_id: str = Field(min_length=1, max_length=64)
    competitor_name: str = Field(default="", max_length=256)
    price_rub: float = Field(ge=0, le=100_000_000)
    price_with_discount_rub: float | None = Field(default=None, ge=0, le=100_000_000)
    in_stock: bool = True
    tracked_product_id: str | None = Field(default=None, max_length=64)
    snapshot_ts: datetime | None = None

    @field_validator("snapshot_ts")
    @classmethod
    def _check_ts(cls, value: datetime | None) -> datetime:
        return _normalize_ts(value)


class ExtensionIngestResult(BaseModel):
    inserted: int
    batch_id: uuid.UUID
